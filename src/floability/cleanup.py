# cleanup.py
"""
Manages subprocess cleanup. Now we send SIGINT to each process so they can do
their own shutdown (e.g. vine_factory removing workers), then we fallback to
terminate() if they're still alive.
"""

import signal
import time
import os
import shutil


class CleanupManager:
    """
    Tracks subprocesses we need to clean up on Ctrl+C or program exit.
    """

    def __init__(self):
        self.subprocesses = []
        self.process_groups = {}
        self.directories = []
        self._cleanup_complete = False

    def register_subprocess(self, proc):
        self.subprocesses.append(proc)
        self.process_groups[id(proc)] = os.getpgid(proc.pid)

    def register_directory(self, directory):
        self.directories.append(directory)

    @property
    def cleanup_complete(self) -> bool:
        return self._cleanup_complete

    def cleanup(self):
        if self._cleanup_complete:
            return
        self._cleanup_complete = True

        print(
            "[cleanup] Sending SIGINT to all subprocesses so they can do their own cleanup..."
        )

        # Capture process groups at registration time. A wrapper such as
        # ``conda run`` can exit before its children, making proc.poll() and
        # os.getpgid(proc.pid) insufficient to determine whether the group is
        # still alive.
        def process_group_exists(pgid):
            try:
                os.killpg(pgid, 0)
                return True
            except ProcessLookupError:
                return False
            except PermissionError:
                return True

        # 1) Send SIGINT
        for proc in self.subprocesses:
            pgid = self.process_groups.get(id(proc))
            if pgid is not None and process_group_exists(pgid):
                print(f"[cleanup] SIGINT -> pid={proc.pid}, pgid={pgid}")
                try:
                    os.killpg(pgid, signal.SIGINT)
                except Exception as e:
                    print(
                        f"[cleanup] Warning: could not send SIGINT to pid={proc.pid}: {e}"
                    )

        # 2) Give them a moment to exit
        time.sleep(2)

        # 3) Terminate any surviving process group, even if its original
        # wrapper/leader has already exited.
        for proc in self.subprocesses:
            pgid = self.process_groups.get(id(proc))
            if pgid is not None and process_group_exists(pgid):
                print(
                    f"[cleanup] Process group {pgid} still alive; sending SIGTERM"
                )
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except Exception as e:
                    print(f"[cleanup] Warning: could not terminate pid={proc.pid}: {e}")

        # Optional: final wait to ensure they're gone
        for proc in self.subprocesses:
            try:
                proc.wait(timeout=2)
            except:
                pass

        for directory in self.directories:
            print(f"[cleanup] Cleaning up directory: {directory}")
            shutil.rmtree(directory, ignore_errors=True)

        print("[cleanup] All subprocesses cleaned up.")


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
