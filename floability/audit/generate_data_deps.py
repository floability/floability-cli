import sys
import os
import re
import yaml

def process_strace_log(file_path, data_dep_list):
    deps = []
    seen = set()
    
    try:
        with open(file_path, 'r') as file:
            for line in file:
                if 'openat' not in line:
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
    excluded_paths = ['/proc', '/sys', '/usr',  '/lib', '/opt', '/tmp', '/var', '/etc']
    excluded_paths_contains = ['/site-packages', '/vine-run-info', '/open_trace.log', '/dask']
    with open(file_path, 'r') as f:
        lines = f.readlines()
        lines = [line.strip() for line in lines]
        lines = [line for line in lines if not any(line.startswith(excluded) for excluded in excluded_paths)]
        lines = [line for line in lines if not any(excluded in line for excluded in excluded_paths_contains)]
    
    return lines


def extract_file_sizes(log_file_name, target_file_list):
    """ 
    This function extracts the file sizes for the necessary files.
    Input: name of the strace log file, and a list of the files.
    Output: a dictionary with file name: file size pairs.
    
    """
    target_paths = set(item.strip() for item in target_file_list if item.strip())

    def path_matches_target(opened_path):
    # This function checks the matching of target files with the opened files 
        return any(opened_path.endswith(target) for target in target_paths)

    open_files = []

# Explore the strace log
    with open(log_file_name, "r") as f:
        for line in f:
            # Match PID
            pid_match = re.match(r'^\s*(\d+)', line)
            if not pid_match:
                continue
            pid = int(pid_match.group(1))
            # Match opened files
            open_match = re.search(r'openat\(.*?"(.*?)".*?= (\d+)', line)
            if open_match:
                path, fd = open_match.groups()
                if path_matches_target(path):
                    open_files.append({"pid": pid, "fd": int(fd), "path": path, "size": "Unknown"})
            # Match file descriptor from fstat
            fstat_match = re.search(r'fstat\((\d+), \{.*?st_size=(\d+)', line)
            if fstat_match:
                fd, size = map(int, fstat_match.groups())
                for entry in reversed(open_files):
                    if entry["pid"] == pid and entry["fd"] == fd and entry["size"] == "Unknown":
                        entry["size"] = size
                        break
            # Match file descriptor from nfstat
            nfstat_match = re.search(r'newfstatat\((\d+), "", \{.*?st_size=(\d+)', line)
            if nfstat_match:
                fd, size = map(int, nfstat_match.groups())
                for entry in reversed(open_files):
                    if entry["pid"] == pid and entry["fd"] == fd and entry["size"] == "Unknown":
                        entry["size"] = size
                        break

    # Deduplicate
    unique_files = {}
    for entry in open_files:
        path = entry["path"]
        size = entry["size"]
        if path not in unique_files or (unique_files[path] == "Unknown" and size != "Unknown"):
            unique_files[path] = size

    return unique_files


def main(file_path, strace_manager, strace_worker):
    # Get the list of data dependencies from the open_trace.log file

    
    data_dep_list = get_list_of_files(file_path)

    # Process the strace logs for manager and worker
    manager_list = process_strace_log(strace_manager, data_dep_list)
    worker_list = process_strace_log(strace_worker, data_dep_list)
    
    # Extract file sizes
    manager_list_with_size = extract_file_sizes(strace_manager, manager_list)
    worker_list_with_size = extract_file_sizes(strace_worker, worker_list)    
    # Write manager dependencies to a file    
    manager_dependencies = [{"name": path, "size": size} for path, size in manager_list_with_size.items()]
    manager_dependencies_yml = {"data_dependencies": manager_dependencies}
    with open('manager_data_dependencies.yml', 'w') as f:
        yaml.dump(manager_dependencies_yml, f, sort_keys=False)    

    # Write worker dependencies to a file    
    worker_dependencies = [{"name": path, "size": size} for path, size in worker_list_with_size.items()]
    worker_dependencies_yml = {"data_dependencies": worker_dependencies}
    with open('worker_data_dependencies.yml', 'w') as f:
        yaml.dump(worker_dependencies_yml, f, sort_keys=False)    


