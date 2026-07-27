"""
Backpack operations for Floability CLI.

Handles backpack initialization (from templates or custom workflows) and validation.
"""

import argparse
import shutil
import sys
from pathlib import Path

from floability.backpack_bootstrap import (
    resolve_backpack_target,
    init_from_template,
    init_from_workflow,
    validate_backpack,
    update_env_from_instance,
)


def run_backpack_command(args: argparse.Namespace) -> None:
    """
    Entry point for 'floability backpack' command.

    Supports subcommands:
    - init: Create a new backpack from template or workflow
    - validate: Validate backpack structure
    """
    sub = getattr(args, "backpack_subcommand", None)

    if sub == "init":
        init_backpack(args)
    elif sub == "validate":
        validate_backpack_cmd(args)
    elif sub == "update-env":
        update_env_backpack_cmd(args)
    else:
        print(f"[floability] Unknown backpack subcommand: {sub}")


def init_backpack(args: argparse.Namespace) -> None:
    """
    Initialize a new backpack.

    Supports two modes:
    1. From template (--from-template taskvine|taskvine-data):
       - Generate complete backpack with starter workflow, environment, compute, data
    2. From custom workflow (--from-workflow <path>):
       - Copy user's workflow, prompt for environment, generate compute/data
    """
    # Resolve backpack target (name or path)
    try:
        backpack_path, backpack_name = resolve_backpack_target(args.name)
    except ValueError as e:
        print(f"[floability] Error: {e}")
        return

    # Check if backpack already exists
    if backpack_path.exists():
        if not args.force:
            print(
                f"[floability] Error: Backpack directory already exists: {backpack_path}"
            )
            print("[floability] Use --force to overwrite")
            return
        else:
            print(
                f"[floability] Removing existing backpack at {backpack_path}"
            )
            shutil.rmtree(backpack_path)

    # Template mode
    if args.from_template:
        try:
            init_from_template(
                backpack_path=backpack_path,
                backpack_name=backpack_name,
                template_variant=args.from_template,  # taskvine or taskvine-data
                use_script=getattr(args, "script", False),
            )
            print_success_message(backpack_path)
        except Exception as e:
            print(f"[floability] Error initializing from template: {e}")
            return

    # Custom workflow mode
    elif args.from_workflow:
        try:
            init_from_workflow(
                backpack_path=backpack_path,
                backpack_name=backpack_name,
                workflow_source=Path(args.from_workflow),
            )
            print_success_message(backpack_path)
        except Exception as e:
            print(f"[floability] Error initializing from workflow: {e}")
            return


def update_env_backpack_cmd(args: argparse.Namespace) -> None:
    """
    Update a backpack's software/environment.yml from a completed instance's conda environment.

    Reads env_dir from the instance's metadata/run.json, exports the conda environment
    (--no-builds), preserves backpack-specific fields (e.g. post_install_script) and
    the existing env name, backs up the old file as old-environment.yml, then writes
    the new environment.yml.

    By default only the versions of packages already listed in the backpack
    environment.yml are patched. With --full the entire dependency list is replaced.
    With --export-lock-file an additional conda-lock.yml (with build strings) is written
    to the software/ directory.
    """
    backpack_path = Path(args.path).resolve()

    try:
        update_env_from_instance(
            instance_ref=args.from_instance,
            backpack_path=backpack_path,
            full=getattr(args, "full", False),
            export_lock_file=getattr(args, "export_lock_file", False),
        )
    except Exception as e:
        print(f"[floability] Error updating environment: {e}")
        sys.exit(1)


def validate_backpack_cmd(args: argparse.Namespace) -> None:
    """
    Validate a backpack structure.

    Checks:
    - Directory exists
    - workflow/ directory and entrypoint file exists
    - software/environment.yml exists and is valid YAML
    - compute/compute.yml exists and is valid YAML
    - data/data.yml (if present) is valid YAML
    """
    backpack_path = Path(args.path).resolve()

    try:
        result = validate_backpack(backpack_path, strict=args.strict)
        print_validation_result(result)
        sys.exit(0 if result["valid"] else 1)
    except Exception as e:
        print(f"[floability] Error validating backpack: {e}")
        sys.exit(1)


def print_success_message(backpack_path: Path) -> None:
    """Print success message with next steps."""
    sep = "=" * 70
    print(f"\n{sep}")
    print("[floability] Backpack created successfully!")
    print(f"[floability] Location: {backpack_path}")
    print(f"\n[floability] Next steps:")
    print(f"[floability]   1. Review and edit the backpack files as needed")
    print(f"[floability]   2. Run: floability backpack validate {backpack_path}")
    print(f"[floability]   3. Then: floability run --backpack {backpack_path}")
    print(sep + "\n")


def print_validation_result(result: dict) -> None:
    """Print validation result summary."""
    sep = "=" * 70
    print(f"\n{sep}")
    print(f"[floability] Backpack Validation: {'VALID' if result['valid'] else 'INVALID'}")
    print(sep)

    if result["valid"]:
        print("[floability] ✓ Backpack structure is valid")
        print(f"[floability]   Path: {result['path']}")
        print(f"[floability]   Workflow: {result.get('workflow_file', 'N/A')}")
        if result.get("has_data"):
            print("[floability]   ✓ data.yml found")
    else:
        print("[floability] ✗ Backpack has issues:")
        for problem in result.get("problems", []):
            print(f"[floability]   - {problem}")

    print(sep + "\n")
