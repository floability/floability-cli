"""
Audit operations for Floability CLI.
"""

from ..audit.audit import audit
from ..audit.cell_level.audit import audit as cell_level_audit
from ..audit.detect_local_files import detect_local_py_files
from ..audit.generate_backpack import generate_backpack


def run_audit_command(args):
    if not args.notebook:
        print("[floability] 'audit' command requires --notebook argument.")
        return

    print(
        f"[floability] Generating environment for notebook: {args.notebook} with kernel: {args.kernel}"
    )

    if args.cell_level:
        cell_level_audit(
            args.notebook, args.kernel, args.manager_name, args.manager_port
        )
        return

    result = audit(
        args.notebook,
        args.kernel,
        args.manager_name,
        args.manager_port,
        conda_env=getattr(args, "conda_env", None),
        data_dirs=getattr(args, "data_dirs", None),
        no_worker=getattr(args, "no_worker", False),
    )

    backpack_name = getattr(args, "backpack_name", None)
    if not backpack_name or not result:
        return

    print(f"\n[floability] Generating backpack: {backpack_name}")

    helpers = detect_local_py_files(
        strace_manager=str(result["strace_manager"]),
        notebook_path=args.notebook,
    )
    if helpers:
        print(f"[floability] Detected {len(helpers)} local helper file(s):")
        for h in helpers:
            print(f"[floability]   {h.name}")
    else:
        print("[floability] No local helper files detected.")

    consolidated_data_deps = result.get("consolidated_data_deps")
    notebook_dir = result.get("notebook_dir")

    has_data = bool(consolidated_data_deps)

    try:
        backpack_path = generate_backpack(
            backpack_name=backpack_name,
            notebook_path=args.notebook,
            manager_env_yml=str(result["manager_environment_yml"]),
            local_helper_files=helpers,
            force=getattr(args, "force", False),
            consolidated_data_deps=consolidated_data_deps,
            notebook_dir=notebook_dir,
        )
        print(f"\n[floability] Backpack created: {backpack_path}")
        print(f"[floability]   workflow/  — notebook + {len(helpers)} helper(s)")
        print(f"[floability]   software/environment.yml — from audit")
        print(f"[floability]   compute/compute.yml — default template (edit before running)")
        if has_data:
            print(f"[floability]   data/data.yml — {len(consolidated_data_deps)} file(s) bundled")
        print(f"\n[floability] Next steps:")
        print(f"[floability]   1. Review compute/compute.yml and adjust worker resources")
        print(f"[floability]   2. floability backpack validate {backpack_path}")
        print(f"[floability]   3. floability run --backpack {backpack_path}")
    except ValueError as e:
        print(f"[floability] Error: {e}")
