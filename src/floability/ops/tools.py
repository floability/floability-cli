"""Storage cleanup operations for the Floability CLI."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections import Counter
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Floability targets Linux HPC systems.
    fcntl = None

from ..instance_lock_manager import (
    are_workers_running,
    get_instance_lock_status,
    read_workers_lock,
)
from ..instance_registry import (
    RegistryError,
    get_recent_base_directories,
    get_registered_instances_status,
    prune_nonexistent_entries,
    seed_base_directories_from_instances,
)

DELETE_STAGING_PREFIX = ".floability-delete-"
BASE_CLEAN_LOCK = ".floability-clean.lock"
DEFAULT_MAX_JOBS = 4


class CleanupPlanError(RuntimeError):
    """Raised when a safe cleanup plan cannot be constructed."""


@dataclass(frozen=True)
class CleanupTarget:
    """One exact filesystem entry selected for deletion."""

    category: str
    path: Path
    container: Path


@dataclass
class BaseCleanupPlan:
    """Reference-aware cleanup plan for one Floability base directory."""

    base_dir: Path
    data_cache_dir: Path
    retained_instances: set[Path] = field(default_factory=set)
    latest_instance: Path | None = None
    protected_data_entries: int = 0
    protected_env_dirs: int = 0
    protected_env_archives: int = 0
    targets: list[CleanupTarget] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def run_tools_command(args) -> int:
    """Dispatch a tools subcommand and return a process exit status."""
    if getattr(args, "tools_subcommand", None) == "clean":
        return _run_clean(args)
    print(
        "[floability tools] Error: no sub-command specified. "
        "Use 'floability tools --help'.",
        file=sys.stderr,
    )
    return 1


def _run_clean(args) -> int:
    """Plan, display, confirm, and execute reference-aware cleanup."""
    try:
        statuses = get_registered_instances_status()
        base_dirs = _select_base_directories(args, statuses)
        jobs = _validated_jobs(getattr(args, "jobs", None))
        data_cache_override = _resolve_data_cache_override(args, base_dirs)

        lock_context = (
            nullcontext()
            if getattr(args, "dry_run", False)
            else _cleanup_locks(base_dirs)
        )
        with lock_context:
            plans = _build_cleanup_plans(
                args,
                base_dirs,
                statuses,
                data_cache_override=data_cache_override,
            )
            _print_cleanup_plan(plans, jobs)

            if getattr(args, "dry_run", False):
                print(
                    "[floability tools clean] Dry run complete. "
                    "No cleanup targets were removed."
                )
                return 0

            targets = [target for plan in plans for target in plan.targets]
            if not targets:
                print("[floability tools clean] Nothing to clean.")
                return 0

            if not getattr(args, "yes", False) and not _confirm_cleanup():
                print("[floability tools clean] Aborted. No files were changed.")
                return 0

            _revalidate_selected_bases_idle(plans, statuses)
            failures = _execute_cleanup_targets(targets, jobs)
            _repair_latest_symlinks(plans)
            prune_nonexistent_entries()
    except (CleanupPlanError, RegistryError, OSError, ValueError) as error:
        print(f"[floability tools clean] Error: {error}", file=sys.stderr)
        return 1

    if failures:
        print(
            f"[floability tools clean] Cleanup incomplete: {failures} "
            "target(s) could not be removed.",
            file=sys.stderr,
        )
        return 1

    print(
        f"[floability tools clean] Clean complete. "
        f"Removed {len(targets)} target(s)."
    )
    return 0


def _select_base_directories(args, statuses: dict[str, dict]) -> list[Path]:
    raw_base = getattr(args, "base_dir", None)
    if raw_base:
        base_dir = Path(raw_base).expanduser().resolve()
        _validate_base_directory(base_dir)
        return [base_dir]

    seed_base_directories_from_instances(statuses)
    registered = get_recent_base_directories()
    if not registered:
        raise CleanupPlanError(
            "no usable base directory was found in Floability's recent-base "
            "registry; provide --base-dir PATH"
        )

    selected = (
        registered
        if getattr(args, "all_registered_bases", False)
        else registered[:1]
    )
    base_dirs = [Path(entry["path"]).resolve() for entry in selected]
    for base_dir in base_dirs:
        _validate_base_directory(base_dir)

    if getattr(args, "all_registered_bases", False):
        print(
            "[floability tools clean] Using all existing base directories found "
            "in Floability's recent-base registry. Older or unregistered bases "
            "may not be included."
        )
    else:
        print(
            "[floability tools clean] Using the most recently used base directory "
            "found in Floability's recent-base registry."
        )
    return base_dirs


def _validate_base_directory(base_dir: Path) -> None:
    if not base_dir.is_dir():
        raise CleanupPlanError(f"base directory does not exist: {base_dir}")
    forbidden = {Path("/").resolve(), Path.home().resolve()}
    if base_dir in forbidden:
        raise CleanupPlanError(
            f"refusing to use unsafe base directory as a cleanup root: {base_dir}"
        )


def _resolve_data_cache_override(args, base_dirs: list[Path]) -> Path | None:
    raw_override = getattr(args, "data_cache_dir", None)
    if not raw_override:
        return None
    if len(base_dirs) != 1:
        raise CleanupPlanError(
            "--data-cache-dir cannot be combined with --all-registered-bases"
        )
    cache_dir = Path(raw_override).expanduser().resolve()
    _validate_cache_root(cache_dir, base_dirs[0])
    return cache_dir


def _validate_cache_root(cache_dir: Path, base_dir: Path) -> None:
    forbidden = {Path("/").resolve(), Path.home().resolve(), base_dir.resolve()}
    if cache_dir in forbidden or cache_dir in base_dir.parents:
        raise CleanupPlanError(
            f"refusing to use unsafe data-cache cleanup root: {cache_dir}"
        )


def _validated_jobs(value) -> int:
    default_jobs = min(os.cpu_count() or 1, DEFAULT_MAX_JOBS)
    jobs = default_jobs if value is None else int(value)
    if jobs < 1:
        raise CleanupPlanError("--jobs must be at least 1")
    return jobs


@contextmanager
def _base_cleanup_lock(base_dir: Path):
    lock_path = base_dir / BASE_CLEAN_LOCK
    with open(lock_path, "a+") as lock_stream:
        if fcntl is not None:
            try:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise CleanupPlanError(
                    f"another cleanup is already active for {base_dir}"
                ) from error
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def _cleanup_locks(base_dirs: list[Path]):
    with ExitStack() as stack:
        for base_dir in sorted(base_dirs, key=str):
            stack.enter_context(_base_cleanup_lock(base_dir))
        yield


def _build_cleanup_plans(
    args,
    base_dirs: list[Path],
    statuses: dict[str, dict],
    *,
    data_cache_override: Path | None,
) -> list[BaseCleanupPlan]:
    scope = _cleanup_scope(args)
    all_instances = {
        base_dir: _discover_instances(base_dir, statuses) for base_dir in base_dirs
    }
    active = {
        instance: reason
        for instances in all_instances.values()
        for instance in instances
        if (reason := _active_instance_reason(instance)) is not None
    }
    if active:
        details = "; ".join(f"{path.name}: {reason}" for path, reason in active.items())
        raise CleanupPlanError(
            "refusing cleanup while selected base directories contain active or "
            f"unverifiable instance ownership ({details})"
        )

    latest_instance = None
    if scope == "keep_last":
        latest_instance = _select_latest_instance(statuses, set(base_dirs))
        if latest_instance is None:
            raise CleanupPlanError(
                "--mode keep-last requires a previously run instance in the "
                "selected base directory"
            )

    plans = []
    for base_dir in base_dirs:
        cache_dir = data_cache_override or (base_dir / "floability-data-cache")
        if data_cache_override is None:
            _validate_cache_root(cache_dir.resolve(), base_dir)
        plans.append(
            _build_base_plan(
                base_dir,
                cache_dir,
                all_instances[base_dir],
                scope,
                latest_instance=latest_instance,
            )
        )

    if scope == "incomplete_only":
        for plan in plans:
            _add_cache_targets(plan, scope, set(), set(), set())
    elif scope != "instances_only":
        retained_instances = {
            instance for plan in plans for instance in plan.retained_instances
        }
        selected_bases = set(base_dirs)
        for status in statuses.values():
            if not status.get("exists") or not status.get("path"):
                continue
            registered_base = Path(status.get("base_dir", "")).resolve()
            if registered_base not in selected_bases:
                retained_instances.add(Path(status["path"]).resolve())

        data_references: set[Path] = set()
        env_dir_references: set[Path] = set()
        env_archive_references: set[Path] = set()
        for instance in sorted(retained_instances, key=str):
            data_refs, env_dirs, env_archives = _read_instance_dependencies(instance)
            data_references.update(data_refs)
            env_dir_references.update(env_dirs)
            env_archive_references.update(env_archives)

        for plan in plans:
            _add_cache_targets(
                plan,
                scope,
                data_references,
                env_dir_references,
                env_archive_references,
            )
    return plans


def _cleanup_scope(args) -> str:
    raw_mode = getattr(args, "mode", None)
    if not raw_mode:
        raise CleanupPlanError(
            "a cleanup mode is required; use --mode and review "
            "'floability tools clean --help'"
        )
    mode = str(raw_mode).replace("-", "_")
    supported = {
        "all",
        "data_only",
        "env_only",
        "data_and_env",
        "instances_only",
        "keep_last",
        "incomplete_only",
    }
    if mode not in supported:
        raise CleanupPlanError(f"unsupported cleanup mode: {raw_mode}")
    return mode


def _discover_instances(base_dir: Path, statuses: dict[str, dict]) -> set[Path]:
    instances = set()
    for path in base_dir.glob("fi_*"):
        if not path.is_symlink() and path.is_dir():
            instances.add(path.resolve())
    for status in statuses.values():
        path_value = status.get("path")
        base_value = status.get("base_dir")
        if not path_value or not base_value or not status.get("exists"):
            continue
        if Path(base_value).resolve() == base_dir:
            path = Path(path_value).resolve()
            if path.is_dir():
                instances.add(path)
    return instances


def _active_instance_reason(instance_dir: Path) -> str | None:
    instance_status = get_instance_lock_status(instance_dir)
    if instance_status["state"] == "active_legacy":
        legacy_pid = (instance_status.get("lock_data") or {}).get("pid")
        return (
            f"legacy instance lock PID {legacy_pid} is live but cannot be "
            "identity-verified"
        )
    if instance_status["state"] in {
        "active",
        "corrupt",
        "unverifiable",
    }:
        return f"instance lock is {instance_status['state']}"

    workers_lock_path = instance_dir / "metadata" / "workers.lock"
    workers_lock = read_workers_lock(instance_dir)
    if workers_lock_path.exists() and workers_lock is None:
        return "worker lock is corrupt or unreadable"
    if workers_lock is not None and are_workers_running(instance_dir):
        return "worker ownership is active"

    metadata_file = instance_dir / "metadata" / "run.json"
    try:
        metadata = json.loads(metadata_file.read_text())
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(metadata, dict):
        return None
    preparation_state = (metadata.get("preparation") or {}).get("state")
    if preparation_state == "preparing":
        return "instance preparation is in progress or incomplete"
    return None


def _select_latest_instance(
    statuses: dict[str, dict], selected_bases: set[Path]
) -> Path | None:
    for status in statuses.values():
        if not status.get("last_run_at") or not status.get("exists"):
            continue
        if Path(status.get("base_dir", "")).resolve() in selected_bases:
            return Path(status["path"]).resolve()
    return None


def _build_base_plan(
    base_dir: Path,
    data_cache_dir: Path,
    instances: set[Path],
    scope: str,
    *,
    latest_instance: Path | None,
) -> BaseCleanupPlan:
    plan = BaseCleanupPlan(
        base_dir=base_dir,
        data_cache_dir=data_cache_dir,
        latest_instance=(
            latest_instance
            if latest_instance is not None and latest_instance.parent == base_dir
            else None
        ),
    )

    delete_instances = scope in {"instances_only", "all", "keep_last"}
    if delete_instances:
        for instance in instances:
            if scope == "keep_last" and instance == latest_instance:
                plan.retained_instances.add(instance)
            elif _safe_instance_target(instance, base_dir):
                plan.targets.append(CleanupTarget("instance", instance, base_dir))
            else:
                plan.retained_instances.add(instance)
                plan.warnings.append(
                    f"retained nonstandard registered instance path: {instance}"
                )
    else:
        plan.retained_instances.update(instances)

    if delete_instances or scope == "incomplete_only":
        plan.targets.extend(_staged_instance_targets(base_dir))
    return plan


def _add_cache_targets(
    plan: BaseCleanupPlan,
    scope: str,
    data_references: set[Path],
    env_dir_references: set[Path],
    env_archive_references: set[Path],
) -> None:
    clean_data = scope in {"data_only", "data_and_env", "all", "keep_last"}
    clean_env = scope in {"env_only", "data_and_env", "all", "keep_last"}
    clean_incomplete = scope == "incomplete_only"

    if clean_data or clean_incomplete:
        _validate_data_cache_layout(plan.data_cache_dir)
        protected, targets = _select_unreferenced_entries(
            plan.data_cache_dir,
            data_references,
            "data cache",
            staged_only=clean_incomplete,
        )
        plan.protected_data_entries = protected
        plan.targets.extend(targets)

    if clean_env or clean_incomplete:
        env_cache_dir = plan.base_dir / "flo_common_env"
        protected, targets = _select_unreferenced_entries(
            env_cache_dir / "extracted_envs",
            env_dir_references,
            "env extracted",
            staged_only=clean_incomplete,
        )
        plan.protected_env_dirs = protected
        plan.targets.extend(targets)

        protected, targets = _select_unreferenced_entries(
            env_cache_dir / "tarballs",
            env_archive_references,
            "env archive",
            staged_only=clean_incomplete,
        )
        plan.protected_env_archives = protected
        plan.targets.extend(targets)


def _safe_instance_target(instance: Path, base_dir: Path) -> bool:
    return (
        not instance.is_symlink()
        and instance.parent == base_dir
        and instance.name.startswith("fi_")
    )


def _read_instance_dependencies(
    instance_dir: Path,
) -> tuple[set[Path], set[Path], set[Path]]:
    metadata_file = instance_dir / "metadata" / "run.json"
    try:
        metadata = json.loads(metadata_file.read_text())
    except (OSError, json.JSONDecodeError, AttributeError) as error:
        raise CleanupPlanError(
            f"cannot determine cache references for retained instance "
            f"{instance_dir}: {error}"
        ) from error
    if not isinstance(metadata, dict):
        raise CleanupPlanError(
            f"run metadata for retained instance must be an object: {metadata_file}"
        )

    environment = metadata.get("environment") or {}
    data = metadata.get("data") or {}
    if not isinstance(environment, dict) or not isinstance(data, dict):
        raise CleanupPlanError(
            f"environment and data metadata must be objects: {metadata_file}"
        )
    cache_dirs = data.get("cache_dirs") or []
    if not isinstance(cache_dirs, list):
        raise CleanupPlanError(
            f"data.cache_dirs must be a list in retained instance: {metadata_file}"
        )

    env_dir = metadata.get("env_dir") or environment.get("env_dir")
    manager_pack = metadata.get("manager_environment_pack") or environment.get(
        "manager_pack"
    )
    worker_pack = metadata.get("worker_environment_pack") or environment.get(
        "worker_pack"
    )

    data_refs = {_resolved_reference(value) for value in cache_dirs if value}
    env_dirs = {_resolved_reference(env_dir)} if env_dir else set()
    env_archives = {
        _resolved_reference(value)
        for value in (manager_pack, worker_pack)
        if value
    }
    return data_refs, env_dirs, env_archives


def _resolved_reference(value) -> Path:
    return Path(value).expanduser().resolve()


def _validate_data_cache_layout(data_cache_dir: Path) -> None:
    """Reject arbitrary directories masquerading as a data-cache root."""
    if not data_cache_dir.exists():
        return
    if not data_cache_dir.is_dir():
        raise CleanupPlanError(f"data-cache root is not a directory: {data_cache_dir}")
    for entry in data_cache_dir.iterdir():
        if entry.name == ".floability-cache.json" or entry.name.startswith(
            DELETE_STAGING_PREFIX
        ):
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", entry.name):
            raise CleanupPlanError(
                "data-cache root contains an entry that does not match "
                f"Floability's cache layout: {entry}"
            )


def _select_unreferenced_entries(
    container: Path,
    references: set[Path],
    category: str,
    *,
    staged_only: bool = False,
) -> tuple[int, list[CleanupTarget]]:
    if not container.is_dir():
        return 0, []
    protected = 0
    targets = []
    for entry in sorted(container.iterdir(), key=lambda path: path.name):
        if entry.name in {BASE_CLEAN_LOCK, ".floability-cache.json"}:
            continue
        if entry.name.startswith(DELETE_STAGING_PREFIX):
            targets.append(CleanupTarget("incomplete/staged", entry, container))
            continue
        if staged_only:
            continue
        if _entry_contains_reference(entry, references):
            protected += 1
        else:
            targets.append(CleanupTarget(category, entry, container))
    return protected, targets


def _entry_contains_reference(entry: Path, references: set[Path]) -> bool:
    entry_resolved = entry.resolve()
    for reference in references:
        if reference == entry_resolved or entry_resolved in reference.parents:
            return True
    return False


def _staged_instance_targets(base_dir: Path) -> list[CleanupTarget]:
    return [
        CleanupTarget("incomplete/staged", path, base_dir)
        for path in sorted(base_dir.glob(f"{DELETE_STAGING_PREFIX}*"))
    ]


def _print_cleanup_plan(plans: list[BaseCleanupPlan], jobs: int) -> None:
    print("[floability tools clean] Cleanup plan")
    for plan in plans:
        counts = Counter(target.category for target in plan.targets)
        print(f"  Base: {plan.base_dir}")
        if plan.latest_instance is not None:
            print(f"    Keep latest run: {plan.latest_instance.name}")
        print(
            "    Keep: "
            f"{len(plan.retained_instances)} instance(s), "
            f"{plan.protected_data_entries} data entry/entries, "
            f"{plan.protected_env_dirs} env dir(s), "
            f"{plan.protected_env_archives} env archive(s)"
        )
        print(
            "    Delete: "
            f"{counts['instance']} instance(s), "
            f"{counts['data cache']} data entry/entries, "
            f"{counts['env extracted']} env dir(s), "
            f"{counts['env archive']} env archive(s), "
            f"{counts['incomplete/staged']} staged/incomplete entry/entries"
        )
        for warning in plan.warnings:
            print(f"    Warning: {warning}")
    print(f"  Parallel deletion jobs: {jobs}")


def _confirm_cleanup() -> bool:
    try:
        return input("Proceed? [y/N] ").strip().lower() in {"y", "yes"}
    except EOFError:
        return False


def _revalidate_selected_bases_idle(
    plans: list[BaseCleanupPlan], statuses: dict[str, dict]
) -> None:
    """Narrow the planning-to-deletion race by checking ownership again."""
    for plan in plans:
        for instance in _discover_instances(plan.base_dir, statuses):
            reason = _active_instance_reason(instance)
            if reason is not None:
                raise CleanupPlanError(
                    f"instance became active after planning: {instance.name}: {reason}"
                )


def _execute_cleanup_targets(targets: list[CleanupTarget], jobs: int) -> int:
    staged_targets: list[tuple[CleanupTarget, Path, bool]] = []
    failures = 0
    for target in targets:
        try:
            _validate_target_boundary(target)
            already_staged = target.path.name.startswith(DELETE_STAGING_PREFIX)
            staged_path = _stage_target(target)
            staged_targets.append((target, staged_path, already_staged))
        except (OSError, subprocess.SubprocessError, CleanupPlanError) as error:
            failures += 1
            print(
                f"[floability tools clean] Warning: could not stage "
                f"{target.path}: {error}",
                file=sys.stderr,
            )

    if failures:
        for target, staged_path, already_staged in reversed(staged_targets):
            if already_staged:
                continue
            try:
                os.replace(staged_path, target.path)
            except OSError as error:
                print(
                    f"[floability tools clean] Warning: could not restore "
                    f"{target.path} after staging failed: {error}",
                    file=sys.stderr,
                )
        return failures

    for target, staged_path, _already_staged in staged_targets:
        try:
            _delete_staged_path(staged_path, jobs)
            print(f"[floability tools clean] Removed {target.category}: {target.path}")
        except (OSError, subprocess.SubprocessError, CleanupPlanError) as error:
            failures += 1
            print(
                f"[floability tools clean] Warning: could not remove "
                f"{target.path}: {error}",
                file=sys.stderr,
            )
    return failures


def _validate_target_boundary(target: CleanupTarget) -> None:
    if target.path.parent.resolve() != target.container.resolve():
        raise CleanupPlanError(
            f"cleanup target is not a direct child of its approved root: {target.path}"
        )
    if target.path.resolve() in {Path("/").resolve(), Path.home().resolve()}:
        raise CleanupPlanError(f"refusing unsafe cleanup target: {target.path}")


def _stage_target(target: CleanupTarget) -> Path:
    if target.path.name.startswith(DELETE_STAGING_PREFIX):
        return target.path
    staged_name = f"{DELETE_STAGING_PREFIX}{uuid.uuid4().hex}-{target.path.name}"
    staged_path = target.container / staged_name
    os.replace(target.path, staged_path)
    return staged_path


def _delete_staged_path(path: Path, jobs: int) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if not path.is_dir():
        return
    _make_directories_writable(path)
    _parallel_unlink_files(path, jobs)
    shutil.rmtree(path)
    if path.exists():
        raise OSError(f"staged cleanup path still exists: {path}")


def _make_directories_writable(path: Path) -> None:
    for root, dirs, _files in os.walk(path, topdown=True, followlinks=False):
        root_path = Path(root)
        root_path.chmod(root_path.stat().st_mode | 0o700)
        for name in dirs:
            directory = root_path / name
            if directory.is_symlink():
                continue
            try:
                directory.chmod(directory.stat().st_mode | 0o700)
            except FileNotFoundError:
                continue


def _parallel_unlink_files(path: Path, jobs: int) -> None:
    required = ("find", "xargs", "rm")
    missing = [command for command in required if shutil.which(command) is None]
    if missing:
        raise CleanupPlanError(
            "parallel cleanup requires these commands on PATH: " + ", ".join(missing)
        )

    find_command = [
        "find",
        str(path),
        "-xdev",
        "(",
        "-type",
        "f",
        "-o",
        "-type",
        "l",
        ")",
        "-print0",
    ]
    remove_command = [
        "xargs",
        "-0",
        "-r",
        "-n",
        "100",
        "-P",
        str(jobs),
        "rm",
        "-f",
        "--",
    ]
    with subprocess.Popen(find_command, stdout=subprocess.PIPE) as find_process:
        assert find_process.stdout is not None
        remove_result = subprocess.run(remove_command, stdin=find_process.stdout)
        find_process.stdout.close()
        find_returncode = find_process.wait()
    if find_returncode != 0:
        raise subprocess.CalledProcessError(find_returncode, find_command)
    if remove_result.returncode != 0:
        raise subprocess.CalledProcessError(remove_result.returncode, remove_command)


def _repair_latest_symlinks(plans: list[BaseCleanupPlan]) -> None:
    for plan in plans:
        if plan.latest_instance is not None and plan.latest_instance.is_dir():
            from ..instance_manager import create_latest_symlink

            create_latest_symlink(
                str(plan.base_dir),
                str(plan.latest_instance),
                verbose=False,
            )
            continue
        symlink = plan.base_dir / "latest_floability_instance"
        if not symlink.is_symlink():
            continue
        try:
            target = symlink.resolve(strict=True)
        except FileNotFoundError:
            symlink.unlink()
            continue
        deleted_instances = {
            cleanup_target.path
            for cleanup_target in plan.targets
            if cleanup_target.category == "instance"
        }
        if target in deleted_instances:
            symlink.unlink()
