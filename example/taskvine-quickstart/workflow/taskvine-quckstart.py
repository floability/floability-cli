# quickstart.py

import ndcctools.taskvine as vine

import os

manager_name = api_key = os.environ.get("VINE_MANAGER_NAME")
print(f"Manager name: {manager_name}")

ports_str = os.environ.get("VINE_MANAGER_PORTS", "9123, 9150")
ports = [int(p.strip()) for p in ports_str.split(",")]
print(f"Ports: {ports}")

# Create a new manager
m = vine.Manager(ports, name=manager_name)
print(f"[manager] Listening on port {m.port}")

# Declare a common input file to be shared by multiple tasks.
f = m.declare_url("https://www.gutenberg.org/cache/epub/2600/pg2600.txt", cache="workflow")

# Submit several tasks using that file.
print("Submitting tasks...")
for keyword in ['needle', 'house', 'water', 'war', 'peace']:
    task = vine.Task(f"grep {keyword} warandpeace.txt | wc")
    task.add_input(f, "warandpeace.txt")
    task.set_cores(1)
    m.submit(task)

# As they complete, display the results:
print("Waiting for tasks to complete...")
while not m.empty():
    task = m.wait(5)
    if task:
        print(f"Task {task.id} completed with result {task.output}")

print("All tasks done.")