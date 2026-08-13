"""Runtime version and installation diagnostics."""

from __future__ import annotations

import importlib.metadata
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__


def concise_version(program: str = "floability") -> str:
    """Return the stable one-line CLI version string."""
    return f"{program} {__version__}"


def _command_version(command: str, *args: str) -> str:
    executable = shutil.which(command)
    if executable is None:
        return "not found"

    try:
        result = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unavailable ({exc})"

    output = (result.stdout or result.stderr).strip().splitlines()
    if output:
        return output[0]
    return f"available at {executable} (exit {result.returncode})"


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def _ndcctools_version() -> str:
    """Return TaskVine's module version, including for Conda installations.

    The conda-forge ``ndcctools`` package provides the ``ndcctools`` Python
    modules without installing Python ``.dist-info`` metadata. Consequently,
    ``importlib.metadata.version("ndcctools")`` alone cannot detect it.
    """
    try:
        from ndcctools import taskvine
    except ImportError:
        return _distribution_version("ndcctools")

    module_version = getattr(taskvine, "__version__", None)
    if module_version:
        return str(module_version)
    return _distribution_version("ndcctools")


def _git_details(package_dir: Path) -> tuple[str, str]:
    repository = package_dir.parent
    if not (repository / ".git").exists() or shutil.which("git") is None:
        return "unavailable", "unavailable"

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        dirty_result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        dirty = "yes" if dirty_result.stdout.strip() else "no"
        return commit, dirty
    except (OSError, subprocess.SubprocessError):
        return "unavailable", "unavailable"


def verbose_version(program: str = "floability") -> str:
    """Return multiline, best-effort build and runtime diagnostics."""
    package_dir = Path(__file__).resolve().parent
    commit, dirty = _git_details(package_dir)

    rows = [
        ("Floability", __version__),
        ("Git commit", commit),
        ("Git dirty", dirty),
        ("Python", platform.python_version()),
        ("Python executable", sys.executable),
        ("Platform", platform.platform()),
        ("Architecture", platform.machine()),
        ("Package location", str(package_dir)),
        ("Conda", _command_version("conda", "--version")),
        ("conda-pack", _command_version("conda-pack", "--version")),
        ("Jupyter", _command_version("jupyter", "--version")),
        ("ndcctools", _ndcctools_version()),
        ("vine_factory", _command_version("vine_factory", "--version")),
        ("vine_worker", _command_version("vine_worker", "--version")),
    ]

    width = max(len(label) for label, _ in rows)
    heading = concise_version(program)
    details = "\n".join(f"{label:<{width}} : {value}" for label, value in rows)
    return f"{heading}\n{details}"
