"""
Distributed Task Processing with TaskVine — Floability Starter Script

This script demonstrates:
  1. Connecting to a TaskVine manager
  2. Defining a distributed worker function
  3. Submitting and collecting tasks

To customize:
  - Edit worker_function() with your own logic
  - Adjust NUM_TASKS and any task parameters
  - Read the TaskVine docs: https://taskvine.readthedocs.io/en/latest/
"""

import os
import time

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
# This runs on distributed worker nodes.  Replace the body with your logic.
# ---------------------------------------------------------------------------

def worker_function(value, sleep_time=1):
    """Double a number after simulating work."""
    time.sleep(sleep_time)
    return {"input": value, "output": value * 2}


# Quick local smoke-test
print(f"[manager] worker_function smoke-test: {worker_function(5, sleep_time=0)}")


# ---------------------------------------------------------------------------
# Submit Tasks
# ---------------------------------------------------------------------------

NUM_TASKS = 20
task_map = {}

for i in range(NUM_TASKS):
    task = vine.PythonTask(worker_function, i, sleep_time=1)
    task_id = m.submit(task)
    task_map[task_id] = i

print(f"[manager] Submitted {len(task_map)} tasks")


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
        print(f"  Task {done.id}: {r['input']} → {r['output']}  worker={done.addrport}")
    else:
        print(f"  Task {done.id} failed: {done.result}")

print(f"\n[manager] All {len(results)} tasks complete.")
