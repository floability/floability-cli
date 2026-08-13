import json
import subprocess
import os
from pathlib import Path
import random
from . import __version__ as floability_version


def send_catalog_update(
    manager_name: str,
    jupyter_port: int,
    run_dir: str,
    event: str = None,
    mode: str = None,
    backpack_name: str = None,
    entrypoint_name: str = None,
):
    """
    Send a catalog update for this Floability instance.
    """
    update_data = {
        "type": "floability",
        "version": floability_version,
        "manager_name": manager_name,
        "event": event if event else "startup",
        "jupyter_port": jupyter_port,
        "run_dir": os.path.abspath(run_dir),
        "mode": mode if mode else "default",
        "entrypoint_name": entrypoint_name if entrypoint_name else "none",
        "backpack": backpack_name if backpack_name else "none",
        "port": -random.randint(
            30000, 60000
        ),  # Catalog update requires a port to uniquely identify entry on host. Making it negative to identify as a pretend port.
    }

    # Create update file
    update_file = os.path.join(run_dir, "catalog_update.json")
    with open(update_file, "w") as f:
        json.dump(update_data, f, indent=2)

    try:
        # Send catalog update
        subprocess.run(
            ["catalog_update", "--file", update_file], check=True, capture_output=True
        )
        print(f"[floability] Sent catalog update with manager name: {manager_name}")
    except subprocess.CalledProcessError as e:
        print(f"[floability] Failed to send catalog update: {e}")
    except FileNotFoundError:
        print(
            "[floability] catalog_update command not found. Install cctools to enable catalog updates."
        )
