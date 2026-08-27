# cleanup.py
"""Manage cleanup of subprocesses and their process groups."""

import os
import shutil
import signal
import time

SIGINT_GRACE_SECONDS = 10
SIGTERM_GRACE_SECONDS = 3
SIGKILL_GRACE_SECONDS = 2
PROCESS_GROUP_POLL_SECONDS = 0.1


class TerminationRequested(Exception):
    """Propagate a termination signal to code that owns durable state."""

    def __init__(self, signal_number: int):
        self.signal_number = signal_number
        super().__init__(f"termination requested by signal {signal_number}")


class CleanupManager:
    """
    Tracks subprocesses we need to clean up on Ctrl+C or program exit.
    """

    def __init__(self, *, process_sigint_grace_seconds=None):
        self.subprocesses = []
        self.process_groups = {}
        self.verified_process_groups = {}
        self.verified_processes = {}
        self.directories = []
        self.cleanup_callbacks = []
        self._cleanup_complete = False
        self._owned_processes_stopped = False
        self._state_reconciled = False
        self.process_sigint_grace_seconds = process_sigint_grace_seconds

    def register_subprocess(self, proc):
        self.subprocesses.append(proc)
        self.process_groups[id(proc)] = os.getpgid(proc.pid)

    def register_process_group(self, pgid):
        """Track an existing process group when no ``Popen`` handle exists."""
        self.process_groups[("pgid", pgid)] = pgid

    def register_verified_process_group(self, pgid, ownership_check):
        """Track a process group that must pass ownership before signaling."""
        self.verified_process_groups[pgid] = ownership_check

    def register_verified_process(self, pid, ownership_check):
        """Track a PID that may be signaled only while ownership is verified.

        ``ownership_check`` returns ``owned``, ``gone``, ``mismatched``, or
        ``unverifiable``. Anything other than ``owned`` or ``gone`` is a safe
        cleanup failure and is never signaled.
        """
        self.verified_processes[pid] = ownership_check

    def register_directory(self, directory):
        self.directories.append(directory)

    def register_cleanup_callback(self, callback):
        """Register state reconciliation to run after each cleanup attempt.

        The callback receives one boolean indicating whether all tracked
        process groups are gone. It may return ``False`` to keep cleanup
        retryable when its own state update could not be completed.
        """
        self.cleanup_callbacks.append(callback)

    @property
    def cleanup_complete(self) -> bool:
        return self._cleanup_complete

    @property
    def owned_processes_stopped(self) -> bool:
        """Whether all tracked process and group targets are confirmed gone."""
        return self._owned_processes_stopped

    @property
    def state_reconciled(self) -> bool:
        """Whether every cleanup state callback completed successfully."""
        return self._state_reconciled

    def cleanup(self):
        """Stop all tracked process groups and remove temporary directories.

        The registered ``Popen`` object may be a short-lived wrapper such as
        ``conda run``. Its children remain members of the process group even
        after that wrapper exits, so completion is determined from the stored
        process-group IDs rather than only from ``Popen.wait()``.

        Returns:
            ``True`` when every tracked process group is gone, otherwise
            ``False``. An incomplete cleanup remains retryable.
        """
        if self._cleanup_complete:
            return True

        print(
            "[cleanup] Sending SIGINT to all subprocesses so they can do "
            "their own cleanup..."
        )

        tracked_groups = set(self.process_groups.values())
        remaining_groups = self._stop_process_groups(tracked_groups)
        remaining_verified_groups = self._stop_verified_process_groups(
            self.verified_process_groups
        )
        remaining_processes = self._stop_verified_processes(
            self.verified_processes
        )
        self._owned_processes_stopped = not (
            remaining_groups
            or remaining_verified_groups
            or remaining_processes
        )

        for directory in self.directories:
            print(f"[cleanup] Cleaning up directory: {directory}")
            shutil.rmtree(directory, ignore_errors=True)

        callbacks_succeeded = self._run_cleanup_callbacks(
            cleanup_succeeded=self._owned_processes_stopped
        )
        self._state_reconciled = callbacks_succeeded

        if remaining_groups:
            groups = ", ".join(str(pgid) for pgid in sorted(remaining_groups))
            print(
                "[cleanup] Warning: cleanup incomplete; process groups still "
                f"alive: {groups}"
            )

        if remaining_verified_groups:
            groups = ", ".join(
                str(pgid) for pgid in sorted(remaining_verified_groups)
            )
            print(
                "[cleanup] Warning: cleanup incomplete; verified process "
                f"groups still alive or ownership became unverifiable: {groups}"
            )

        if remaining_processes:
            processes = ", ".join(
                str(pid) for pid in sorted(remaining_processes)
            )
            print(
                "[cleanup] Warning: cleanup incomplete; verified processes "
                f"still alive or ownership became unverifiable: {processes}"
            )

        if not callbacks_succeeded:
            print("[cleanup] Warning: cleanup state reconciliation incomplete.")

        if (
            remaining_groups
            or remaining_verified_groups
            or remaining_processes
            or not callbacks_succeeded
        ):
            return False

        self._cleanup_complete = True
        print("[cleanup] All subprocesses cleaned up.")
        return True

    def _run_cleanup_callbacks(self, cleanup_succeeded):
        callbacks_succeeded = True
        for callback in self.cleanup_callbacks:
            try:
                if callback(cleanup_succeeded) is False:
                    callbacks_succeeded = False
            except Exception as error:
                callbacks_succeeded = False
                print(
                    "[cleanup] Warning: cleanup state callback failed: "
                    f"{error}"
                )
        return callbacks_succeeded

    def _stop_process_groups(self, process_groups):
        """Apply the graceful-to-forced shutdown sequence to tracked groups."""
        remaining_groups = self._existing_process_groups(process_groups)
        shutdown_stages = (
            (signal.SIGINT, "SIGINT", SIGINT_GRACE_SECONDS),
            (signal.SIGTERM, "SIGTERM", SIGTERM_GRACE_SECONDS),
            (signal.SIGKILL, "SIGKILL", SIGKILL_GRACE_SECONDS),
        )

        for stage_number, (sig, signal_name, timeout) in enumerate(shutdown_stages):
            if not remaining_groups:
                break

            if stage_number > 0:
                groups = ", ".join(
                    str(pgid) for pgid in sorted(remaining_groups)
                )
                print(
                    f"[cleanup] Process groups {groups} still alive; "
                    f"sending {signal_name}"
                )

            self._signal_process_groups(remaining_groups, sig, signal_name)
            remaining_groups = self._wait_for_process_groups(
                remaining_groups,
                timeout=timeout,
            )

        return remaining_groups

    def _stop_verified_processes(self, processes):
        """Stop direct process targets without ever signaling changed identity."""
        remaining = dict(processes)
        unsafe = set()
        sigint_grace = (
            self.process_sigint_grace_seconds
            if self.process_sigint_grace_seconds is not None
            else SIGINT_GRACE_SECONDS
        )
        shutdown_stages = (
            (signal.SIGINT, "SIGINT", sigint_grace),
            (signal.SIGTERM, "SIGTERM", SIGTERM_GRACE_SECONDS),
            (signal.SIGKILL, "SIGKILL", SIGKILL_GRACE_SECONDS),
        )

        for stage_number, (sig, signal_name, timeout) in enumerate(shutdown_stages):
            if not remaining:
                break
            if stage_number > 0:
                pids = ", ".join(str(pid) for pid in sorted(remaining))
                print(
                    f"[cleanup] Processes {pids} still alive; "
                    f"sending {signal_name}"
                )

            eligible = {}
            for pid, ownership_check in remaining.items():
                state = self._verified_process_state(ownership_check)
                if state == "gone":
                    continue
                if state != "owned":
                    unsafe.add(pid)
                    print(
                        f"[cleanup] Refusing to signal pid={pid}: "
                        f"ownership is {state}."
                    )
                    continue
                eligible[pid] = ownership_check

            remaining = self._signal_verified_processes(
                eligible,
                sig,
                signal_name,
            )
            remaining, became_unsafe = self._wait_for_verified_processes(
                remaining,
                timeout,
            )
            unsafe.update(became_unsafe)

        return set(remaining) | unsafe

    def _stop_verified_process_groups(self, process_groups):
        """Stop process groups only while their saved ownership still matches."""
        remaining = dict(process_groups)
        unsafe = set()
        shutdown_stages = (
            (signal.SIGINT, "SIGINT", SIGINT_GRACE_SECONDS),
            (signal.SIGTERM, "SIGTERM", SIGTERM_GRACE_SECONDS),
            (signal.SIGKILL, "SIGKILL", SIGKILL_GRACE_SECONDS),
        )

        for stage_number, (sig, signal_name, timeout) in enumerate(shutdown_stages):
            if not remaining:
                break
            if stage_number > 0:
                groups = ", ".join(str(pgid) for pgid in sorted(remaining))
                print(
                    f"[cleanup] Process groups {groups} still alive; "
                    f"sending {signal_name}"
                )

            eligible = {}
            for pgid, ownership_check in remaining.items():
                state = self._verified_process_state(ownership_check)
                if state == "gone":
                    continue
                if state != "owned":
                    unsafe.add(pgid)
                    print(
                        f"[cleanup] Refusing to signal pgid={pgid}: "
                        f"ownership is {state}."
                    )
                    continue
                eligible[pgid] = ownership_check

            remaining = self._signal_verified_process_groups(
                eligible,
                sig,
                signal_name,
            )
            remaining, became_unsafe = self._wait_for_verified_processes(
                remaining,
                timeout,
            )
            unsafe.update(became_unsafe)

        return set(remaining) | unsafe

    @staticmethod
    def _verified_process_state(ownership_check):
        try:
            return ownership_check()
        except Exception as error:
            print(
                "[cleanup] Warning: process ownership check failed: "
                f"{error}"
            )
            return "unverifiable"

    def _signal_verified_processes(self, processes, sig, signal_name):
        still_owned = {}
        for pid, ownership_check in processes.items():
            state = self._verified_process_state(ownership_check)
            if state == "gone":
                continue
            if state != "owned":
                # The caller's next verification records this as incomplete.
                still_owned[pid] = ownership_check
                continue
            print(f"[cleanup] {signal_name} -> pid={pid}")
            try:
                os.kill(pid, sig)
                still_owned[pid] = ownership_check
            except ProcessLookupError:
                pass
            except Exception as error:
                print(
                    f"[cleanup] Warning: could not send {signal_name} to "
                    f"pid={pid}: {error}"
                )
                still_owned[pid] = ownership_check
        return still_owned

    def _signal_verified_process_groups(
        self,
        process_groups,
        sig,
        signal_name,
    ):
        still_owned = {}
        for pgid, ownership_check in process_groups.items():
            state = self._verified_process_state(ownership_check)
            if state == "gone":
                continue
            if state != "owned":
                still_owned[pgid] = ownership_check
                continue
            print(f"[cleanup] {signal_name} -> pgid={pgid}")
            try:
                os.killpg(pgid, sig)
                still_owned[pgid] = ownership_check
            except ProcessLookupError:
                pass
            except Exception as error:
                print(
                    f"[cleanup] Warning: could not send {signal_name} to "
                    f"pgid={pgid}: {error}"
                )
                still_owned[pgid] = ownership_check
        return still_owned

    def _wait_for_verified_processes(self, processes, timeout):
        deadline = time.monotonic() + timeout
        remaining = dict(processes)
        unsafe = set()
        while remaining and time.monotonic() < deadline:
            time.sleep(
                min(
                    PROCESS_GROUP_POLL_SECONDS,
                    max(0, deadline - time.monotonic()),
                )
            )
            next_remaining = {}
            for pid, ownership_check in remaining.items():
                state = self._verified_process_state(ownership_check)
                if state == "owned":
                    next_remaining[pid] = ownership_check
                elif state != "gone":
                    unsafe.add(pid)
            remaining = next_remaining
        return remaining, unsafe

    @staticmethod
    def _process_group_exists(pgid):
        try:
            os.killpg(pgid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def _existing_process_groups(self, process_groups):
        return {
            pgid for pgid in process_groups if self._process_group_exists(pgid)
        }

    def _wait_for_process_groups(self, process_groups, timeout):
        """Wait until groups disappear, returning any that remain."""
        deadline = time.monotonic() + timeout
        remaining_groups = self._existing_process_groups(process_groups)

        while remaining_groups and time.monotonic() < deadline:
            self._reap_exited_wrappers()
            time.sleep(
                min(PROCESS_GROUP_POLL_SECONDS, max(0, deadline - time.monotonic()))
            )
            remaining_groups = self._existing_process_groups(remaining_groups)

        self._reap_exited_wrappers()
        return self._existing_process_groups(remaining_groups)

    def _reap_exited_wrappers(self):
        for proc in self.subprocesses:
            try:
                proc.poll()
            except Exception:
                # Cleanup must continue for the stored process group even when
                # a custom process wrapper cannot be polled.
                pass

    def _signal_process_groups(self, process_groups, sig, signal_name):
        for pgid in sorted(process_groups):
            if not self._process_group_exists(pgid):
                continue
            print(f"[cleanup] {signal_name} -> pgid={pgid}")
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                pass
            except Exception as error:
                print(
                    f"[cleanup] Warning: could not send {signal_name} to "
                    f"pgid={pgid}: {error}"
                )


def install_signal_handlers(cleanup_manager: CleanupManager):
    """
    Install signal handlers with conventional process exit semantics.

    SIGINT becomes ``KeyboardInterrupt`` and SIGTERM becomes
    ``TerminationRequested`` so the command that owns durable state can
    finalize it before the CLI returns 130 or 143.
    """
    def signal_handler(sig, frame):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

        if sig == signal.SIGINT:
            raise KeyboardInterrupt

        raise TerminationRequested(sig)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
