# cleanup.py
"""
Manages subprocess cleanup. Now we send SIGINT to each process so they can do
their own shutdown (e.g. vine_factory removing workers), then we fallback to
terminate() if they're still alive.
"""

import signal
import sys
import time
import os
import shutil


class CleanupManager:
    """
    Tracks subprocesses we need to clean up on Ctrl+C or program exit.
    """

    def __init__(self):
        self.subprocesses = []
        self.directories = []

    def register_subprocess(self, proc):
        self.subprocesses.append(proc)

    def register_directory(self, directory):
        self.directories.append(directory)

    def cleanup(self):
        print(
            "[cleanup] Sending SIGINT to all subprocesses so they can do their own cleanup..."
        )

        # 1) Send SIGINT
        for proc in self.subprocesses:
            if proc.poll() is None:  # still running
                print(
                    f"[cleanup] SIGINT -> pid={proc.pid}, pgid={os.getpgid(proc.pid)}"
                )
                try:
                    # proc.send_signal(signal.SIGINT)
                    os.killpg(os.getpgid(proc.pid), signal.SIGINT)
                except Exception as e:
                    print(
                        f"[cleanup] Warning: could not send SIGINT to pid={proc.pid}: {e}"
                    )

        # 2) Give them a moment to exit
        time.sleep(2)

        # 3) Anyone still running, we call terminate()
        for proc in self.subprocesses:
            if proc.poll() is None:
                print(
                    f"[cleanup] Process pid={proc.pid} still alive; calling terminate()"
                )
                try:
                    # proc.terminate()
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
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
    Installs a signal handler so that Ctrl+C (SIGINT) or SIGTERM triggers
    the CleanupManager's cleanup(), then exits.
    """
    import signal

    def signal_handler(sig, frame):
        # Temporarily disable the signal handler to prevent recursion
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print(f"[cleanup] Caught signal {sig}, initiating cleanup...")
        cleanup_manager.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
