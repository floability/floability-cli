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


class CleanupManager:
    """
    Tracks subprocesses we need to clean up on Ctrl+C or program exit.
    """

    def __init__(self):
        self.subprocesses = []
        self.process_groups = {}
        self.directories = []
        self.cleanup_callbacks = []
        self._cleanup_complete = False

    def register_subprocess(self, proc):
        self.subprocesses.append(proc)
        self.process_groups[id(proc)] = os.getpgid(proc.pid)

    def register_process_group(self, pgid):
        """Track an existing process group when no ``Popen`` handle exists."""
        self.process_groups[("pgid", pgid)] = pgid

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

        for directory in self.directories:
            print(f"[cleanup] Cleaning up directory: {directory}")
            shutil.rmtree(directory, ignore_errors=True)

        callbacks_succeeded = self._run_cleanup_callbacks(
            cleanup_succeeded=not remaining_groups
        )

        if remaining_groups:
            groups = ", ".join(str(pgid) for pgid in sorted(remaining_groups))
            print(
                "[cleanup] Warning: cleanup incomplete; process groups still "
                f"alive: {groups}"
            )

        if not callbacks_succeeded:
            print("[cleanup] Warning: cleanup state reconciliation incomplete.")

        if remaining_groups or not callbacks_succeeded:
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

    SIGINT becomes ``KeyboardInterrupt`` so the CLI can record an interrupted
    workflow before cleaning up and returning 130. SIGTERM performs immediate
    cleanup and exits with 143 (128 + signal 15).
    """
    def signal_handler(sig, frame):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

        if sig == signal.SIGINT:
            raise KeyboardInterrupt

        print(f"[cleanup] Caught signal {sig}, initiating cleanup...")
        cleanup_manager.cleanup()
        raise SystemExit(128 + sig)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
