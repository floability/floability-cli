#!/usr/bin/env python3
"""
Test runner helper for Floability tests.

Usage:
    python tests/run_tests.py list              # List all tests
    python tests/run_tests.py all               # Run all tests
    python tests/run_tests.py unit              # Run unit tests only
    python tests/run_tests.py network           # Run network tests only
    python tests/run_tests.py pelican           # Run pelican tests only
    python tests/run_tests.py http              # Run HTTP tests only
    python tests/run_tests.py handler           # Run data handler tests only
    python tests/run_tests.py <test_name>       # Run specific test by name
"""

import sys
import subprocess
from pathlib import Path


def run_command(cmd, description):
    """Run a command and print description."""
    print(f"\n{'='*70}")
    print(f"  {description}")
    print(f"{'='*70}\n")
    result = subprocess.run(cmd, shell=True)
    return result.returncode


def list_tests():
    """List all available tests."""
    cmd = "pytest --collect-only -q"
    return run_command(cmd, "Available Tests")


def run_all():
    """Run all tests."""
    cmd = "pytest tests/ -v"
    return run_command(cmd, "Running All Tests")


def run_unit():
    """Run unit tests only (fast, no network)."""
    cmd = "pytest tests/ -m unit -v"
    return run_command(cmd, "Running Unit Tests (No Network)")


def run_network():
    """Run network tests only."""
    cmd = "pytest tests/ -m network -v"
    return run_command(cmd, "Running Network Tests")


def run_pelican():
    """Run pelican file utils tests."""
    cmd = "pytest tests/test_pelican_file_utils.py tests/test_data_handler.py -v"
    return run_command(cmd, "Running Pelican Tests")


def run_http():
    """Run HTTP file utils tests."""
    cmd = "pytest tests/test_http_file_utils.py tests/test_data_handler_http.py -v"
    return run_command(cmd, "Running HTTP Tests")


def run_handler():
    """Run all data handler tests."""
    cmd = "pytest tests/test_data_handler.py tests/test_data_handler_http.py -v"
    return run_command(cmd, "Running All Data Handler Tests")


def run_specific(test_name):
    """Run a specific test by name."""
    cmd = f"pytest -k {test_name} -v -s"
    return run_command(cmd, f"Running Tests Matching: {test_name}")


def show_help():
    """Show usage help."""
    print(__doc__)
    print("\nExamples:")
    print("  python tests/run_tests.py list")
    print("  python tests/run_tests.py all")
    print("  python tests/run_tests.py network")
    print("  python tests/run_tests.py download")
    print("  python tests/run_tests.py test_metadata_accessible_file")


def main():
    if len(sys.argv) < 2:
        show_help()
        return 1
    
    command = sys.argv[1].lower()
    
    commands = {
        'list': list_tests,
        'all': run_all,
        'unit': run_unit,
        'network': run_network,
        'pelican': run_pelican,
        'http': run_http,
        'handler': run_handler,
        'help': show_help,
        '-h': show_help,
        '--help': show_help,
    }
    
    if command in commands:
        return commands[command]()
    else:
        # Treat as test name pattern
        return run_specific(command)


if __name__ == '__main__':
    sys.exit(main())
