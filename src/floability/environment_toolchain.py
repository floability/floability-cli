"""Resolve tools and commands for Floability Python environments."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_ENVIRONMENT_CREATORS = ("auto", "conda", "pixi")


class EnvironmentToolResolutionError(RuntimeError):
    """Raised when no compatible executable can satisfy an environment plan."""


@dataclass(frozen=True)
class EnvironmentTool:
    """One resolved implementation of an environment lifecycle capability."""

    capability: str
    family: str
    executable: str | None
    version: str | None = None

    def as_metadata(self) -> dict[str, str | None]:
        return {
            "family": self.family,
            "executable": self.executable,
            "version": self.version,
        }


@dataclass(frozen=True)
class EnvironmentPlan:
    """Resolved tools for one Python environment specification."""

    environment_type: str
    spec_format: str
    creator: EnvironmentTool
    artifact_format: str
    packer: EnvironmentTool
    unpacker: EnvironmentTool
    runner: EnvironmentTool

    def as_metadata(self) -> dict[str, object]:
        return {
            "type": self.environment_type,
            "spec_format": self.spec_format,
            "creator": self.creator.as_metadata(),
            "artifact_format": self.artifact_format,
            "packer": self.packer.as_metadata(),
            "unpacker": self.unpacker.as_metadata(),
            "runner": self.runner.as_metadata(),
        }


def _is_executable(path: str | os.PathLike[str] | None) -> bool:
    if not path:
        return False
    candidate = Path(path).expanduser()
    return candidate.is_file() and os.access(candidate, os.X_OK)


def _first_executable(candidates: Sequence[str | None]) -> str | None:
    seen: set[str] = set()
    for raw_candidate in candidates:
        if not raw_candidate:
            continue
        candidate = str(Path(raw_candidate).expanduser())
        if candidate in seen:
            continue
        seen.add(candidate)
        if _is_executable(candidate):
            return str(Path(candidate).resolve())
    return None


def _probe_version(executable: str, *arguments: str) -> str:
    try:
        result = subprocess.run(
            [executable, *arguments],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    output = (result.stdout or result.stderr or "").strip().splitlines()
    return output[0].strip() if output else "unknown"


def discover_conda_executable(
    *,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    python_executable: str | os.PathLike[str] | None = sys.executable,
) -> str | None:
    """Find Conda through its activation hint or PATH."""
    environment = os.environ if environ is None else environ
    sibling = (
        str(Path(python_executable).resolve().parent / "conda")
        if python_executable
        else None
    )
    return _first_executable((environment.get("CONDA_EXE"), which("conda"), sibling))


def discover_pixi_executable(
    *,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    home: Path | None = None,
    python_executable: str | os.PathLike[str] | None = sys.executable,
) -> str | None:
    """Find Pixi on PATH or in its common per-user installation locations."""
    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    pixi_home = environment.get("PIXI_HOME")
    pixi_home_binary = (
        str(Path(pixi_home).expanduser() / "bin" / "pixi") if pixi_home else None
    )
    sibling = (
        str(Path(python_executable).resolve().parent / "pixi")
        if python_executable
        else None
    )
    return _first_executable(
        (
            which("pixi"),
            sibling,
            pixi_home_binary,
            str(user_home / ".pixi" / "bin" / "pixi"),
        )
    )


def discover_conda_pack_executable(
    *,
    which: Callable[[str], str | None] = shutil.which,
    python_executable: str | os.PathLike[str] | None = sys.executable,
) -> str | None:
    sibling = (
        str(Path(python_executable).resolve().parent / "conda-pack")
        if python_executable
        else None
    )
    return _first_executable((which("conda-pack"), sibling))


def resolve_environment_plan(
    creator_preference: str | None = "auto",
    *,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    home: Path | None = None,
    python_executable: str | os.PathLike[str] | None = sys.executable,
) -> EnvironmentPlan:
    """Resolve a complete initial Python-environment toolchain.

    The automatic policy intentionally preserves Conda when available. Pixi is
    the fallback and can be requested explicitly.
    """
    preference = (creator_preference or "auto").strip().lower()
    if preference not in SUPPORTED_ENVIRONMENT_CREATORS:
        choices = ", ".join(SUPPORTED_ENVIRONMENT_CREATORS)
        raise EnvironmentToolResolutionError(
            f"Unsupported environment creator {preference!r}. Choose one of: {choices}."
        )

    conda = discover_conda_executable(
        environ=environ,
        which=which,
        python_executable=python_executable,
    )
    pixi = discover_pixi_executable(
        environ=environ,
        which=which,
        home=home,
        python_executable=python_executable,
    )

    if preference == "conda":
        creator_family, creator_executable = "conda", conda
    elif preference == "pixi":
        creator_family, creator_executable = "pixi", pixi
    elif conda:
        creator_family, creator_executable = "conda", conda
    else:
        creator_family, creator_executable = "pixi", pixi

    if not creator_executable:
        if preference == "auto":
            raise EnvironmentToolResolutionError(
                "No supported Python environment creator was found. Floability "
                "looked for Conda and Pixi. Install one of them, activate the "
                "Floability environment, and verify with "
                "'floability --version --verbose'."
            )
        raise EnvironmentToolResolutionError(
            f"{creator_family.capitalize()} was requested to create this Python "
            f"environment, but no {creator_family} executable was found. Add it "
            "to PATH and verify with 'floability --version --verbose'."
        )

    packer_executable = discover_conda_pack_executable(
        which=which,
        python_executable=python_executable,
    )
    if not packer_executable:
        raise EnvironmentToolResolutionError(
            "The conda-pack artifact builder was not found. Install conda-pack "
            "in the Floability environment and verify with "
            "'floability --version --verbose'."
        )

    creator_version = _probe_version(creator_executable, "--version")
    packer_version = _probe_version(packer_executable, "--version")
    return EnvironmentPlan(
        environment_type="python",
        spec_format="conda-yaml",
        creator=EnvironmentTool(
            capability="create",
            family=creator_family,
            executable=creator_executable,
            version=creator_version,
        ),
        artifact_format="conda-pack",
        packer=EnvironmentTool(
            capability="pack",
            family="conda-pack",
            executable=packer_executable,
            version=packer_version,
        ),
        unpacker=EnvironmentTool(
            capability="unpack",
            family="conda-unpack",
            executable=None,
            version=None,
        ),
        runner=EnvironmentTool(
            capability="run",
            family="prefix-activation",
            executable="/bin/bash",
            version=None,
        ),
    )


def print_environment_plan(plan: EnvironmentPlan, spec_path: str | Path) -> None:
    """Print a compact, user-visible account of the selected toolchain."""
    creator_version = plan.creator.version or "unknown version"
    packer_version = plan.packer.version or "unknown version"
    print("[environment] Resolved environment plan")
    print(f"[environment] Type          : {plan.environment_type}")
    print(f"[environment] Specification : {plan.spec_format} ({spec_path})")
    print(f"[environment] Creator       : {plan.creator.family} ({creator_version})")
    print(f"[environment] Artifact      : {plan.artifact_format}")
    print(f"[environment] Packer        : {plan.packer.family} ({packer_version})")
    print(f"[environment] Runtime       : {plan.runner.family}")


_PREFIX_RUN_SCRIPT = r"""
prefix=$1
shift
export CONDA_PREFIX="$prefix"
export CONDA_DEFAULT_ENV="$prefix"
export CONDA_SHLVL="${CONDA_SHLVL:-1}"
export PATH="$prefix/bin${PATH:+:$PATH}"
if [ -f "$prefix/conda-meta/state" ] && [ -x "$prefix/bin/python" ]; then
    eval "$("$prefix/bin/python" -c '
import json
import pathlib
import re
import shlex
import sys

try:
    state = json.loads(pathlib.Path(sys.argv[1]).read_text())
except (OSError, ValueError):
    state = {}
for key, value in state.get("env_vars", {}).items():
    if isinstance(key, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        print(f"export {key}={shlex.quote(str(value))}")
' "$prefix/conda-meta/state")"
fi
if [ -d "$prefix/etc/conda/activate.d" ]; then
    for activation_script in "$prefix"/etc/conda/activate.d/*.sh; do
        [ -e "$activation_script" ] || continue
        . "$activation_script"
    done
fi
exec "$@"
""".strip()


def build_prefix_run_command(
    environment_prefix: str | os.PathLike[str], command: Sequence[str]
) -> list[str]:
    """Run an argv vector with prefix activation, without requiring Conda."""
    if not command:
        raise ValueError("environment command must not be empty")
    prefix = str(Path(environment_prefix).expanduser().resolve())
    return [
        "/bin/bash",
        "-c",
        _PREFIX_RUN_SCRIPT,
        "floability-prefix-run",
        prefix,
        *[str(argument) for argument in command],
    ]


def format_prefix_run_command(
    environment_prefix: str | os.PathLike[str],
    command: Sequence[str],
) -> str:
    """Return a concise, shell-escaped description of a prefix command."""
    rendered_command = shlex.join([str(argument) for argument in command])
    return f"{rendered_command}  [environment: {environment_prefix}]"
