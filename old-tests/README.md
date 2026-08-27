# Floability Test Suite

Comprehensive tests for Floability CLI data operations.

## Setup

Install pytest:
```bash
pip install pytest pytest-timeout
```

## Running Tests

### All tests
```bash
pytest tests/ -v
```

### Unit tests only (fast, no network)
```bash
pytest tests/ -m unit -v
```

### Network tests (requires network access)
```bash
pytest tests/ -m network -v
```

### Skip slow tests
```bash
pytest tests/ -m "not slow" -v
```

### Specific test file
```bash
pytest tests/test_pelican_file_utils.py -v
pytest tests/test_data_handler.py -v
```

### With output capture disabled (see print statements)
```bash
pytest tests/ -v -s
```

### Generate HTML coverage report
```bash
pytest tests/ --cov=floability.data --cov-report=html
open htmlcov/index.html
```

## Test Structure

```
tests/
├── __init__.py
├── conftest.py                      # Shared fixtures and configuration
├── test_pelican_file_utils.py      # Low-level Pelican operations
├── test_http_file_utils.py          # Low-level HTTP operations
├── test_data_handler.py             # High-level data operations (Pelican)
├── test_data_handler_http.py        # High-level data operations (HTTP)
├── README.md                        # This file
└── fixtures/
    └── data/
        ├── pelican_single_item.yml  # Single Pelican file test spec
        ├── pelican_nonexistent.yml  # Non-existent Pelican file test spec
        ├── http_single_item.yml     # Single HTTP file test spec (Gutenberg)
        └── http_nonexistent.yml     # Non-existent HTTP file test spec
```

## Test Markers

- `@pytest.mark.unit` - Fast unit tests, no network required
- `@pytest.mark.network` - Tests requiring network access to Pelican servers
- `@pytest.mark.slow` - Long-running tests (downloads, etc.)
- `@pytest.mark.integration` - Full system integration tests

## Test Data

Tests use two data sources:

### Pelican (may be offline)
- URL: `pelican://disc-head-002.crc.nd.edu:443/nd/disc2/apps/floability/examples/cms-physics-dv5/data/samples/diboson/zz/nano_mc2017_6.root`
- Size: 190634 bytes
- Checksum: `sha256:4c976188f38ffbd755267acb9d5b431b9208c7376afa5a26f9a62412e2f33bb0`

### HTTP (Project Gutenberg - always available)
- URL: `https://www.gutenberg.org/cache/epub/64317/pg64317.txt` (The Great Gatsby)
- Size: 306594 bytes
- Checksum: `sha256:e6b7897aa8498b8dac4df0664827f857bc01135c3d9311adb820979bbc44b763`

## Cleanup

Tests automatically clean up downloaded files in temporary directories after each test.

## Troubleshooting

### Network timeouts
If tests fail due to network timeouts, increase timeout in test specs or skip network tests:
```bash
pytest tests/ -m "not network" -v
```

### Pelican server unavailable
If Pelican tests fail, skip them and run HTTP tests:
```bash
pytest tests/test_http_file_utils.py -v
pytest tests/test_data_handler_http.py -v
```

Check server liveness:
```bash
pytest tests/test_pelican_file_utils.py::TestPelicanServerLiveness -v
pytest tests/test_http_file_utils.py::TestHttpServerAccess -v
```
