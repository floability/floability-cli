import os
import re
import sys
import yaml

def process_strace_log(file_path):
    manager_packages = []
    seen_manager = set()
    
    try:
        with open(file_path, 'r') as file:
            for line in file:
                if 'openat' not in line or 'site-packages' not in line:
                    continue
                    
                try:
                    start = line.index('"') + 1
                    end = line.index('"', start)
                    full_path = line[start:end]
                    path_parts = full_path.split('/')
                    
                    try:
                        site_packages_idx = path_parts.index('site-packages')
                        if site_packages_idx + 1 < len(path_parts):
                            package_name = path_parts[site_packages_idx + 1]
                            
                            if site_packages_idx + 2 >= len(path_parts):
                                continue
                            package_dir = '/'.join(path_parts[:site_packages_idx + 2])
                            
                            if package_name not in seen_manager and not package_name.startswith('_'):
                                if re.match(r'^[a-zA-Z0-9_.-]+-\d+(\.\d+)*(-py\d+(\.\d+)*)?(\.egg)$', package_name):
                                    package_name = re.split(r'-\d+', package_name)[0]
                                
                                if package_name.endswith('.egg-info') or package_name.endswith('.dist-info'):
                                    package_name = package_name.rsplit('-', 2)[0]
                      
                                seen_manager.add(package_name)
                                version = find_package_version(package_dir)
                                package_entry = {
                                    'package': package_name,
                                    'path': package_dir,
                                    'version': version if version else None
                                }
                                manager_packages.append(package_entry)
                    except ValueError:
                        continue
                        
                except ValueError:
                    continue
                    
        return manager_packages
        
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found")
        return [], []
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        return [], []

def find_package_version(package_dir):
    try:
        for (dirpath, dirnames, filenames) in os.walk(package_dir):
            potential_files = [f for f in filenames if 'version' in f.lower()] + ['__init__.py']
            
            for version_file in potential_files:
                if version_file in filenames:
                    try:
                        with open(os.path.join(dirpath, version_file), 'r') as f:
                            lines = f.readlines()
                            for line in lines:
                                version_match = re.search(r'^_*version_*\s*=[\s]*[\'"]([^\'"]+)[\'"]', line)
                                if version_match:
                                    version = version_match.group(1).strip()
                                    if version and version[0].isdigit():
                                        return version
                    except Exception as e:
                        print(f"Error reading {version_file} in {dirpath}: {str(e)}")
                        continue
            break
        return None
        
    except Exception as e:
        print(f"Error finding version for {package_dir}: {str(e)}")
        return None

def generate_requirements_yml(manager_packages, worker_packages, output_file="requirements.yml"):
    try:
        def format_dependency(entry):
            return entry['package']

        manager_deps = sorted(list(set([format_dependency(x) for x in manager_packages])))
        worker_deps = sorted(list(set([format_dependency(x) for x in worker_packages])))

        yml_data = {
            'manager-dependencies': manager_deps,
            'worker-dependencies': worker_deps
        }

        with open(output_file, 'w') as f:
            yaml.dump(yml_data, f, default_flow_style=False, sort_keys=False)

        print(f"Generated {output_file} successfully")

    except Exception as e:
        print(f"Error generating {output_file}: {str(e)}")

def generate_requirements_txt(manager_packages, worker_packages, output_worker_file="worker_requirements.txt", output_manager_file="manager_requirements.txt"):
    try:
        def format_dependency(entry):
            return entry['package'] + '==' + entry['version'] if entry['version'] else entry['package']

        manager_deps = sorted(list(set([format_dependency(x) for x in manager_packages])))
        worker_deps = sorted(list(set([format_dependency(x) for x in worker_packages])))

        with open(output_manager_file, 'w') as f:
            f.write("# Manager dependencies\n")
            for dep in manager_deps:
                f.write(f"{dep}\n")
        print(f"Generated {output_manager_file} successfully")
        
        with open(output_worker_file, 'w') as f:
            f.write("\n# Worker dependencies\n")
            for dep in worker_deps:
                f.write(f"{dep}\n")

        print(f"Generated {output_worker_file} successfully")

    except Exception as e:
        print(f"Error generating requirements file: {str(e)}")

def main(manager_log_file, worker_log_file):
    
    manager_packages = process_strace_log(manager_log_file)
    worker_packages = process_strace_log(worker_log_file)
    
    if manager_packages or worker_packages:
        
        # generate requirements
        generate_requirements_txt(manager_packages, worker_packages)
        
        
    else:
        print("No packages found or error occurred")