"""
Distributed File Processing with TaskVine — Floability Starter Script

This script demonstrates:
  1. Connecting to a TaskVine manager
  2. Declaring and staging input files to workers
  3. Processing files in parallel across workers
  4. Collecting and summarising results

To customize:
  - Edit worker_function() with your own logic
  - Adjust DATA_DIR to point at your data
  - Read the TaskVine docs: https://cctools.readthedocs.io/en/latest/taskvine/
"""

import glob
import os

import ndcctools.taskvine as vine


# ---------------------------------------------------------------------------
# Setup: Manager Connection
# TaskVine manager name and ports are injected by Floability as env vars.
# ---------------------------------------------------------------------------

def _parse_ports(ports_str: str) -> list:
    ports = [int(p.strip()) for p in ports_str.split(",") if p.strip()]
    if not ports:
        raise ValueError("No valid ports provided in VINE_MANAGER_PORTS")
    return ports


manager_name = os.environ.get("VINE_MANAGER_NAME")
manager_ports = _parse_ports(os.environ.get("VINE_MANAGER_PORTS", "9123,9150"))

print(f"[manager] Manager name:  {manager_name}")
print(f"[manager] Manager ports: {manager_ports}")

m = vine.Manager(manager_ports, name=manager_name)
print(f"[manager] Listening on port {m.port}")


# ---------------------------------------------------------------------------
# Worker Function
# Reads a file and returns its byte size.  Replace with your own logic.
# ---------------------------------------------------------------------------

def worker_function(file_path):
    """Return byte-size metadata for a file."""
    import os as _os

    if not _os.path.exists(file_path):
        return {"file": file_path, "error": "File not found"}

    return {
        "file": file_path,
        "size_bytes": _os.path.getsize(file_path),
    }


print("[manager] worker_function defined.")


# ---------------------------------------------------------------------------
# Discover Input Files
# ---------------------------------------------------------------------------

DATA_DIR = "data/text_data"

files = glob.glob(os.path.join(DATA_DIR, "*")) if os.path.isdir(DATA_DIR) else []
print(f"[manager] Found {len(files)} file(s) in {DATA_DIR}/")

if not files:
    raise RuntimeError(
        f"No files found in {DATA_DIR}. "
        "Check that data has been staged (floability run will do this automatically)."
    )


# ---------------------------------------------------------------------------
# Submit Tasks
# ---------------------------------------------------------------------------

declared = {path: m.declare_file(path) for path in files}
task_map = {}

for file_path in files:
    t = vine.PythonTask(worker_function, file_path)
    t.add_input(declared[file_path], file_path)
    tid = m.submit(t)
    task_map[tid] = file_path

print(f"[manager] Submitted {len(task_map)} task(s)")


# ---------------------------------------------------------------------------
# Collect Results
# ---------------------------------------------------------------------------

results = []

while not m.empty():
    done = m.wait(5)
    if not done:
        continue
    if done.successful():
        r = done.output
        r["task_id"] = done.id
        results.append(r)
        print(f"  Task {done.id}: {r}  worker={done.addrport}")
    else:
        print(f"  Task {done.id} failed: {done.result}")

total_size = sum(r.get("size_bytes", 0) for r in results)
print(f"\n[manager] All {len(results)} task(s) completed — {total_size} bytes processed")
