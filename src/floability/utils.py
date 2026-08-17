import os
import time
import datetime
import socket
import getpass
import logging
import ipaddress
import threading
import urllib.request
from collections import namedtuple

import tarfile
from pathlib import Path
 
 
# --- module-level caches (each expensive lookup runs at most once) -----------
_FQDN_CACHE = None
_CANDIDATES_CACHE = None
SYSTEM_INFORMATION = None
 
# A candidate address plus how we found it and whether direct (non-tunnel)
# access from outside is plausible.
AccessCandidate = namedtuple("AccessCandidate", ["address", "source", "direct_ok"])
 
_INTERNAL_SUFFIXES = (".local", ".internal", ".ec2.internal", ".localdomain")


def get_conda_executable():
    """Return the real Conda executable, including from shell activation."""
    return os.environ.get("CONDA_EXE") or "conda"
 
 
# --- primitives --------------------------------------------------------------
def get_local_ip():
    """Primary outbound-interface IP. On a cloud VM this is the *private* IP.
 
    Uses a UDP "connect" which sends no packets — it only makes the kernel
    pick the interface that would route to the internet.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception as e:
        print(f"[utils] Warning: could not determine local IP: {e}")
        return None
    finally:
        s.close()
 
 
def _is_public_ip(ip):
    """True only for a globally-routable IP. False for private/loopback/etc."""
    try:
        addr = ipaddress.ip_address(ip)
        return not (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_unspecified
            or addr.is_reserved
            or addr.is_multicast
        )
    except ValueError:
        return False
 
 
def _looks_external(name):
    """True if `name` looks like a real, externally-meaningful hostname.
 
    Deliberately does NOT resolve the name: an HPC login node's FQDN is the
    right thing to advertise even when it resolves to a private IP internally.
    Obvious internal/cloud-internal names are excluded so they never leak out.
    """
    name = (name or "").strip().lower().rstrip(".")
    if not name or name == "localhost" or "." not in name:
        return False
    return not name.endswith(_INTERNAL_SUFFIXES)

def _system_fqdn(timeout=2.0):
    """Cached socket.getfqdn(), guarded by a watchdog so it cannot hang us.
 
    getfqdn() does a reverse-DNS lookup that can stall for a long time on a
    misconfigured network. We run it in a daemon thread and fall back to the
    (instant, local) short hostname if it doesn't return within `timeout`.
    """
    global _FQDN_CACHE
    if _FQDN_CACHE is not None:
        return _FQDN_CACHE
 
    result = {"fqdn": None}
 
    def _resolve():
        try:
            result["fqdn"] = socket.getfqdn()
        except Exception as e:
            print(f"[utils] Warning: getfqdn() failed with error: {e}")
 
    t = threading.Thread(target=_resolve, daemon=True)
    t.start()
    t.join(timeout)
    if result["fqdn"] is None:
        print(f"[utils] Warning: getfqdn() did not return within {timeout} seconds. Using short hostname instead.")
 
    _FQDN_CACHE = result["fqdn"] or socket.gethostname()
    return _FQDN_CACHE


# --- cloud (AWS EC2) ---------------------------------------------------------
def _probe_imds(timeout=0.3):
    """Fast TCP check for the EC2 metadata endpoint.
 
    Returns almost instantly on non-cloud hosts where 169.254.169.254 is not
    routable, so we only pay the metadata round-trip when we're plausibly on EC2.
    Also works inside containers on EC2, where a DMI/SMBIOS check would miss.
    """
    try:
        with socket.create_connection(("169.254.169.254", 80), timeout=timeout):
            return True
    except Exception:
        return False
 
 
def _get_cloud_public_ip():
    """Public IPv4 from AWS EC2 IMDSv2, or None if not on EC2 / no public IP."""
    if not _probe_imds():
        return None
    base = "http://169.254.169.254/latest"
    try:
        token = urllib.request.urlopen(
            urllib.request.Request(
                f"{base}/api/token",
                method="PUT",
                headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            ),
            timeout=1.0,
        ).read().decode()
        ip = urllib.request.urlopen(
            urllib.request.Request(
                f"{base}/meta-data/public-ipv4",
                headers={"X-aws-ec2-metadata-token": token},
            ),
            timeout=1.0,
        ).read().decode().strip()
        return ip if (ip and _is_public_ip(ip)) else None
    except Exception as e:
        print(f"[utils] Warning: EC2 metadata lookup failed: {e}")
        return None
 
 
# --- resolution --------------------------------------------------------------
def get_access_candidates():
    """Ordered list of AccessCandidate, best first. Computed once and cached.
 
    Always returns at least one candidate.
    """
    global _CANDIDATES_CACHE
    if _CANDIDATES_CACHE is not None:
        return _CANDIDATES_CACHE
 
    candidates = []
 
    override = os.environ.get("FLOABILITY_ACCESS_HOST")
    if override:
        candidates.append(AccessCandidate(override.strip(), "FLOABILITY_ACCESS_HOST override", True))
 
    cloud_ip = _get_cloud_public_ip()
    if cloud_ip:
        candidates.append(AccessCandidate(cloud_ip, "cloud public IP (EC2 metadata)", True))
 
    fqdn = _system_fqdn()
    if _looks_external(fqdn):
        candidates.append(AccessCandidate(fqdn, "hostname (FQDN)", True))
 
    local_ip = get_local_ip()
    if local_ip and _is_public_ip(local_ip):
        candidates.append(AccessCandidate(local_ip, "public local IP", True))
    elif local_ip:
        candidates.append(AccessCandidate(local_ip, "local network IP", False))
 
    if not candidates:
        candidates.append(AccessCandidate("localhost", "fallback", False))
 
    for c in candidates:
        print(f"[utils] access candidate: {c.address} [{c.source}]")
 
    _CANDIDATES_CACHE = candidates
    return _CANDIDATES_CACHE
 
 
def get_access_address():
    """Single best-guess address for external users (the top candidate)."""
    return get_access_candidates()[0].address
 
 
def get_system_information():
    """Cached system info dict, including the resolved access address."""
    global SYSTEM_INFORMATION
    if SYSTEM_INFORMATION is None:
        candidates = get_access_candidates()
        SYSTEM_INFORMATION = {
            "username": getpass.getuser(),
            "hostname": socket.gethostname(),
            "fqdn": _system_fqdn(),
            "ip_address": get_local_ip(),                 # internal / private
            "access_address": candidates[0].address,      # advertise this
            "access_candidates": [c._asdict() for c in candidates],
        }
    return SYSTEM_INFORMATION

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
