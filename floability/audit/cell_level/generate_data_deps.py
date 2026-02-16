def process_strace_log(file_path, data_dep_list):
    deps = []
    seen = set()

    try:
        with open(file_path, "r") as file:
            for line in file:
                if "openat" not in line:
                    continue

                start = line.index('"') + 1
                end = line.index('"', start)
                full_path = line[start:end].strip()

                # check if path is in data_dep_list
                if not any(dep == full_path for dep in data_dep_list):
                    continue
                # check if path is in seen
                if full_path in seen:
                    continue
                seen.add(full_path)
        return seen
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found")
        return set()
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        return set()


def get_list_of_files(file_path):
    # Read the list of files from the file
    excluded_paths = ["/proc", "/sys", "/usr", "/lib", "/opt", "/tmp", "/var", "/etc"]
    excluded_paths_contains = [
        "/site-packages",
        "/vine-run-info",
        "/open_trace.log",
        "/dask",
        "89101756618",
        "7ffdc7bb937",
    ]
    with open(file_path, "r") as f:
        lines = f.readlines()
        lines = [line.strip() for line in lines]
        lines = [
            line
            for line in lines
            if not any(line.startswith(excluded) for excluded in excluded_paths)
        ]
        lines = [
            line
            for line in lines
            if not any(excluded in line for excluded in excluded_paths_contains)
        ]

    return lines


import sys
import os


def main(file_path, strace_manager, strace_worker):
    # Get the list of data dependencies from the open_trace.log file

    data_dep_list = get_list_of_files(file_path)

    # Process the strace logs for manager and worker
    manager_list = process_strace_log(strace_manager, data_dep_list)
    worker_set = process_strace_log(strace_worker, data_dep_list)

    # Write manager dependencies to a file
    with open("manager_data_dependencies.txt", "w") as manager_file:
        for item in manager_list:
            manager_file.write(f"{item}\n")

    # Write worker dependencies to a file
    with open("worker_data_dependencies.txt", "w") as worker_file:
        for item in worker_set:
            worker_file.write(f"{item}\n")
