# HTTP Tests Summary

HTTP tests added to complement Pelican tests (which may be offline).

## New Test Files

### 1. **test_http_file_utils.py** - Low-level HTTP operations
   - `TestHttpFileMetadata` (3 tests)
     - ✅ Test metadata fetch for accessible file
     - ✅ Test metadata structure validation
     - ❌ Test non-existent file handling
   
   - `TestHttpFileDownload` (5 tests)
     - ✅ Test basic download
     - ✅ Test checksum validation
     - ✅ Test custom filename
     - ✅ Test overwrite=False (skip existing)
     - ✅ Test overwrite=True (force re-download)
   
   - `TestHttpServerAccess` (1 test)
     - ✅ Test server liveness

   **Total: 9 tests**

### 2. **test_data_handler_http.py** - High-level HTTP data operations
   - `TestCheckDataFromSpecHTTP` (2 tests)
     - ✅ Test check returns True for accessible file
     - ❌ Test non-existent file returns False
   
   - `TestFetchDataFromSpecHTTP` (4 tests)
     - ✅ Test basic fetch
     - ✅ Test file integrity (checksum)
     - ✅ Test cache_mode='symlink'
     - ✅ Test cache_mode='copy'
   
   - `TestVerifyDataFromSpecHTTP` (2 tests)
     - ✅ Test verify downloads and validates
     - ❌ Test wrong checksum fails
   
   - `TestExecuteDefaultDataOperationHTTP` (1 test)
     - ✅ Test execute with policy='fetch'

   **Total: 9 tests**

## Test Data

**Source**: Project Gutenberg (always available)
- File: The Great Gatsby by F. Scott Fitzgerald
- URL: `https://www.gutenberg.org/cache/epub/64317/pg64317.txt`
- Size: 306,594 bytes (~300KB)
- Checksum: `sha256:e6b7897aa8498b8dac4df0664827f857bc01135c3d9311adb820979bbc44b763`

## Running HTTP Tests

```bash
# All HTTP tests
pytest tests/test_http_file_utils.py tests/test_data_handler_http.py -v

# Using helper scripts
python tests/run_tests.py http
./tests/run_tests.sh http

# Individual test files
pytest tests/test_http_file_utils.py -v
pytest tests/test_data_handler_http.py -v

# Specific test
pytest tests/test_http_file_utils.py::TestHttpFileDownload::test_download_basic -v
```

## Test Coverage

### HTTP File Utils Tests
- ✅ Metadata operations (3 tests)
- ✅ Download operations (5 tests)
- ✅ Server access (1 test)

### HTTP Data Handler Tests
- ✅ Check operations (2 tests)
- ✅ Fetch operations (4 tests)
- ✅ Verify operations (2 tests)
- ✅ Default execution (1 test)

**Total HTTP Tests: 18**

## Comparison with Pelican Tests

| Feature | Pelican Tests | HTTP Tests | Notes |
|---------|---------------|------------|-------|
| Low-level utils | 13 tests | 9 tests | HTTP simpler (no resume, etc.) |
| Data handler | 23 tests | 9 tests | HTTP streamlined |
| Total | 36 tests | 18 tests | HTTP 50% fewer tests |
| Network required | Yes | Yes | Both require internet |
| Server reliability | ⚠️ May be offline | ✅ Always available | Gutenberg stable |

## Key Differences

1. **Simplified**: HTTP tests focus on core functionality
2. **Reliable**: Project Gutenberg is stable and public
3. **Smaller file**: 300KB vs 190KB (comparable)
4. **Public data**: No authentication needed
5. **Text file**: Easier to inspect/debug

## When to Use

### Use HTTP tests when:
- ✅ Pelican server is offline
- ✅ Testing core data operations
- ✅ Need reliable CI/CD tests
- ✅ Learning the test framework

### Use Pelican tests when:
- ✅ Testing Pelican-specific features
- ✅ Testing with production data types
- ✅ Validating HPC workflows
- ✅ Server is available

## Quick Start

```bash
# Check if HTTP server is accessible
./tests/run_tests.sh server

# Run all HTTP tests
./tests/run_tests.sh http

# Run specific HTTP test
pytest tests/test_http_file_utils.py::TestHttpFileDownload::test_download_basic -v -s
```
