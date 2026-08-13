import re
import sys
import os
from .generate_requirements import process_strace_log as process_strace_log_code
from .generate_data_deps import get_list_of_files
from .generate_data_deps import process_strace_log as process_strace_log_data
import yaml


def process_cell_level_strace_log(file_path, open_trace_log):

    manager_packages = []
    manager_data_dependencies = []
    list_of_data_files = get_list_of_files(open_trace_log)
    try:
        with open(file_path, "r") as file:
            start_string = "starting with 7ffdc7bb937"
            end_string = "ending with 89101756618"
            curr_index = 0
            content = file.read()
            while True:
                start_index = content.find(start_string, curr_index)
                if start_index == -1:
                    break

                start_index += len(start_string)
                end_index = content.find(end_string, start_index)
                if end_index == -1:
                    break

                with open("tmp.txt", "w") as f:
                    f.write(content[start_index:end_index])
                    manager_packages.append(process_strace_log_code("tmp.txt"))
                    manager_data_dependencies.append(
                        process_strace_log_data("tmp.txt", list_of_data_files)
                    )
                curr_index = end_index + len(end_string)

        return manager_packages, manager_data_dependencies

    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found")
        return []
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        return []


def generate_yml_file(packages, data_dependencies, notebook_name, output_file):
    # using pyyaml library to generate yml file

    def format_dependency(entry):
        return (
            entry["package"] + "==" + entry["version"]
            if entry["version"]
            else entry["package"]
        )

    with open(output_file, "w") as f:
        yaml.dump(
            {
                "notebook_name": notebook_name,
                "cells": [
                    {
                        "cell_number": i + 1,
                        "code_dependencies": [
                            format_dependency(package)
                            for package in packages[i]  # Format the package entry
                        ],
                        "data_dependencies": [
                            dependency for dependency in data_dependencies[i]
                        ],  # Add data dependencies if any
                    }
                    for i, _ in enumerate(packages)
                ],
            },
            f,
            default_flow_style=False,
        )


def main(manager_log_file, notebook_path, open_trace_log):

    print("Generating cell level dependencies")
    notebook_name = notebook_path.split("/")[-1]
    packages, data_dependencies = process_cell_level_strace_log(
        manager_log_file, open_trace_log
    )

    generate_yml_file(
        packages,
        data_dependencies,
        notebook_name,
        output_file="cell_level_dependencies.yml",
    )
