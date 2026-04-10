import os
import time
import datetime
import getpass
import socket
import tarfile
from pathlib import Path

SYSTEM_INFORMATION = None


def create_unique_directory(
    base_dir=".", prefix="fi", max_attempts=10
):
    base_dir = os.path.expanduser(base_dir)
    attempt = 0

    while attempt < max_attempts:
        attempt += 1
        try:
            timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f")
            unique_dir = os.path.join(base_dir, f"{prefix}_{timestamp}")
            os.makedirs(unique_dir, exist_ok=False)

            return unique_dir

        except FileExistsError:
            print(f"Collision (unlikely) on attempt {attempt}. Retrying...")
            time.sleep(0.1)

        except OSError as e:
            print(f"OS Error on attempt {attempt}: {e}")
            raise

    raise RuntimeError(
        f"Failed to create a unique directory after {max_attempts} attempts."
    )


def normalize_cli_base_dir(raw_base: str | None) -> Path:
    """Normalize a CLI-provided base_dir value.

    Rules:
      - If `raw_base` is None, empty, or '.', default to `~/floability-base-dir`.
      - Expand user (~) for provided values.
      - Ensure the directory exists (create parents as needed).

    Returns a resolved `Path` instance.
    """
    if raw_base is None or str(raw_base).strip() == "" or str(raw_base).strip() == ".":
        base = (Path.home() / "floability-base-dir").resolve()
    else:
        base = Path(os.path.expanduser(str(raw_base))).resolve()

    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Best-effort: if creation fails, just return the path object
        pass

    return base


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # Connect to a public DNS server (Google)
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except Exception as e:
        print(f"Error getting local IP: {e}")
        return None


def get_system_information():
    global SYSTEM_INFORMATION
    if SYSTEM_INFORMATION is None:
        SYSTEM_INFORMATION = {
            "username": getpass.getuser(),
            "hostname": socket.gethostname(),
            "ip_address": get_local_ip(),
        }

    return SYSTEM_INFORMATION


def safe_extract_tar(tar_file: Path, dest_dir: Path) -> None:
    """
    Safely extract the contents of tar_file into dest_dir.
    This prevents files from escaping the intended extraction directory.
    Handles conda-pack files with absolute symlinks appropriately.
    """

    print(f"Extracting '{tar_file}' into '{dest_dir}'...")

    with tarfile.open(tar_file, "r:*") as tar:

        def is_within_directory(base: Path, target: Path) -> bool:
            return str(target.resolve()).startswith(str(base.resolve()))

        for member in tar.getmembers():
            member_path = dest_dir.joinpath(member.name)
            if not is_within_directory(dest_dir, member_path):
                raise Exception(
                    f"Tar extraction error: {member.name} is outside {dest_dir}"
                )

        # For conda-pack files, we need to handle symlinks with absolute paths
        # These are generally safe debug files (like gdb auto-load files)
        try:
            tar.extractall(path=dest_dir)
        except tarfile.AbsoluteLinkError as e:
            # Skip problematic symlink files - they're usually debug files and not essential
            print(f"[utils] Skipping absolute symlink in conda-pack: {e}")
            print("[utils] Extracting files individually, skipping problematic symlinks")
            
            # Extract files one by one, skipping the problematic ones
            for member in tar.getmembers():
                try:
                    tar.extract(member, path=dest_dir)
                except tarfile.AbsoluteLinkError as skip_error:
                    print(f"[utils] Skipping problematic file: {member.name}")
                    continue

    print(f"Extraction complete for '{tar_file}'.")


def update_env_vars_in_conda(
    env_dir: str, manager_name: str, manager_ports: str, additional_env_vars: str
):
    """
    Adds/updates the VINE_MANAGER_NAME environment variable in the
    conda environment's activation script.
    """

    env_vars_dir = os.path.join(env_dir, "etc", "conda", "activate.d")
    os.makedirs(env_vars_dir, exist_ok=True)
    env_vars_file = os.path.join(env_vars_dir, "env_vars.sh")

    with open(env_vars_file, "a", encoding="utf-8") as f:
        f.write(f"\nexport VINE_MANAGER_NAME={manager_name}\n")
        f.write(f"export VINE_MANAGER_PORTS={manager_ports}\n")

        if additional_env_vars:
            for pair in additional_env_vars.split(","):
                if "=" in pair:
                    key, value = pair.split("=")
                    f.write(f"export {key.strip()}={value.strip()}\n")

                    print(
                        f"[environment] Added {key.strip()}={value.strip()} to {env_vars_file}"
                    )

    print(
        f"[environment] Updated environment variable VINE_MANAGER_NAME={manager_name} in {env_vars_file}"
    )
    print(
        f"[environment] Updated environment variable VINE_MANAGER_PORTS={manager_ports} in {env_vars_file}"
    )
