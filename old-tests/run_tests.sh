#!/bin/bash
# Quick test runner shortcuts for Floability tests

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Floability Test Runner${NC}\n"

case "$1" in
    list)
        echo "Listing all available tests..."
        pytest --collect-only -q
        ;;
    
    all)
        echo "Running all tests..."
        pytest tests/ -v
        ;;
    
    unit)
        echo "Running unit tests (no network)..."
        pytest tests/ -m unit -v
        ;;
    
    network)
        echo "Running network tests..."
        pytest tests/ -m network -v
        ;;
    
    fast)
        echo "Running fast tests (no network, no slow)..."
        pytest tests/ -m "unit and not slow" -v
        ;;
    
    slow)
        echo "Running slow tests..."
        pytest tests/ -m slow -v
        ;;
    
    pelican)
        echo "Running Pelican tests..."
        pytest tests/test_pelican_file_utils.py tests/test_data_handler.py -v
        ;;
    
    http)
        echo "Running HTTP tests..."
        pytest tests/test_http_file_utils.py tests/test_data_handler_http.py -v
        ;;
    
    s3)
        echo "Running S3 tests..."
        pytest tests/test_s3_file_utils.py tests/test_data_handler_s3.py -v
        ;;
    
    handler)
        echo "Running all data handler tests..."
        pytest tests/test_data_handler.py tests/test_data_handler_http.py tests/test_data_handler_s3.py -v
        ;;
    
    check)
        echo "Running check_data_from_spec tests..."
        pytest -k "check" -v
        ;;
    
    fetch)
        echo "Running fetch_data_from_spec tests..."
        pytest -k "fetch" -v
        ;;
    
    verify)
        echo "Running verify_data_from_spec tests..."
        pytest -k "verify" -v
        ;;
    
    cache)
        echo "Running cache-related tests..."
        pytest -k "cache" -v
        ;;
    
    download)
        echo "Running download tests..."
        pytest -k "download" -v
        ;;
    
    metadata)
        echo "Running metadata tests..."
        pytest -k "metadata" -v
        ;;
    
    server)
        echo "Testing server liveness (Pelican + HTTP)..."
        pytest tests/test_pelican_file_utils.py::TestPelicanServerLiveness tests/test_http_file_utils.py::TestHttpServerAccess -v
        ;;
    
    coverage)
        echo "Running tests with coverage report..."
        pytest tests/ --cov=floability.data --cov-report=html --cov-report=term
        echo -e "\n${GREEN}Coverage report: htmlcov/index.html${NC}"
        ;;
    
    help|--help|-h)
        cat << EOF
Usage: ./tests/run_tests.sh [command]

Commands:
  list         List all available tests
  all          Run all tests
  unit         Run unit tests (no network)
  network      Run network tests
  fast         Run fast tests only
  slow         Run slow tests
  pelican      Run Pelican tests (file utils + handler)
  http         Run HTTP tests (file utils + handler)
  s3           Run S3 tests (file utils + handler)
  handler      Run all data handler tests
  check        Run check_data_from_spec tests
  fetch        Run fetch_data_from_spec tests
  verify       Run verify_data_from_spec tests
  cache        Run cache-related tests
  download     Run download tests
  metadata     Run metadata tests
  server       Test server liveness (Pelican + HTTP)
  coverage     Run tests with coverage report
  help         Show this help

Examples:
  ./tests/run_tests.sh list
  ./tests/run_tests.sh unit
  ./tests/run_tests.sh network
  ./tests/run_tests.sh pelican
  ./tests/run_tests.sh cache

For running specific tests:
  pytest tests/test_pelican_file_utils.py::TestPelicanFileMetadata::test_metadata_accessible_file -v

For filtering by name:
  pytest -k "download and not slow" -v
EOF
        ;;
    
    *)
        echo "Unknown command: $1"
        echo "Run './tests/run_tests.sh help' for usage"
        exit 1
        ;;
esac
