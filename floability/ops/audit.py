"""
Audit operations for Floability CLI.
"""

from ..audit.audit import audit
from ..audit.cell_level.audit import audit as cell_level_audit


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
    else:
        audit(args.notebook, args.kernel, args.manager_name, args.manager_port)
