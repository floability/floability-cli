# S3 Directory Download Implementation Summary

## Overview
Implemented S3 directory download and caching support in Floability CLI, mirroring the Pelican directory download feature.

## Changes Made

### 1. S3 File Utils (`floability/data/s3_file_utils.py`)

Added two new functions:

#### `is_s3_directory(uri, anonymous=None)`
- Checks if an S3 URI represents a directory (prefix with multiple objects)
- Detection logic:
  1. If URI ends with "/", assume directory
  2. Otherwise, list up to 2 objects with the prefix
  3. If exactly one object with matching key → file
  4. Otherwise (multiple objects or different key) → directory
- Returns `True` if directory, `False` otherwise

#### `s3_directory_download(uri, dest_dir, ...)`
- Downloads entire S3 directory recursively
- Uses `s3_list_objects()` to get all files
- Downloads each file preserving directory structure
- Supports:
  - Overwrite mode
  - Resume support
  - Progress bars
  - Anonymous access
  - Structure preservation (can flatten if desired)
- Returns Path to destination directory

### 2. Data Handler (`floability/data/data_handler.py`)

Updated two functions to support S3 directories:

#### `_attempt_fetch_source()`
- Added S3 directory detection using three-tier priority:
  1. Explicit `source_object_type` field
  2. URL trailing slash
  3. Metadata check via `is_s3_directory()`
- If directory: calls `s3_directory_download()` with target_path as dest_dir
- If file: calls `s3_file_download()` with target_path as filename

#### `_download_to_cache()` (in `_build_cache_entry`)
- Added same S3 directory detection logic
- If directory: downloads to cache_file (which is a directory path)
- If file: downloads to cache_file.parent with cache_file.name
- Consistent with Pelican directory handling

### 3. Imports
- Updated `data_handler.py` imports to include:
  - `s3_directory_download`
  - `is_s3_directory`

### 4. Documentation & Examples

Created:
- `example/S3_DIRECTORY_DOWNLOAD.md`: Comprehensive documentation
- `example/s3-directory-examples.yml`: Example data specs
- `scripts/test-s3-dir-download.py`: Test script with 4 test cases

## Test URL
`s3://floability/dv5-sample-data/`

## Test Script
`scripts/test-s3-dir-download.py`

Tests:
1. S3 directory detection
2. Object listing
3. Directory download
4. Caching with data handler

## Usage Example

```yaml
- name: dv5_data
  target_location: data/dv5
  source: s3://floability/dv5-sample-data/
  source_type: s3
  source_object_type: directory  # Optional
```

## Cache Structure

```
cache/
├── cached_data/
│   └── data/
│       └── dv5/          # Full target_location path
│           ├── file1.root
│           └── subdir/
│               └── file2.root
└── .meta.json
```

## Detection Priority

1. **Explicit field**: `source_object_type: "directory"`
2. **Trailing slash**: Source URL ends with `/`
3. **Metadata check**: Calls `is_s3_directory()` to check S3

## Anonymous Access

Set environment variable:
```bash
export AWS_NO_SIGN_REQUEST=true
```

Or in data spec (future enhancement):
```yaml
source_config:
  anonymous: true
```

## Consistency with Pelican

The S3 implementation exactly mirrors the Pelican directory download:
- Same detection methods
- Same cache structure (cached_data/{target_location})
- Same source_object_type field
- Same function signatures and behavior

## Running Tests

```bash
conda activate floability-env
python scripts/test-s3-dir-download.py
```

Or you can test manually and report results.

## Next Steps (Optional)

1. Add parallel downloads for S3 directories
2. Add bandwidth limiting
3. Add progress tracking for overall directory download
4. Add support for source_config field for per-item anonymous setting
5. Add integration tests with actual backpacks

## Files Modified

1. `floability/data/s3_file_utils.py`: Added 2 functions (~150 lines)
2. `floability/data/data_handler.py`: Updated 2 functions (~50 lines changed)
3. `example/S3_DIRECTORY_DOWNLOAD.md`: Created documentation
4. `example/s3-directory-examples.yml`: Created examples
5. `scripts/test-s3-dir-download.py`: Created test script (~250 lines)

## Verification Needed

The test script should verify:
- ✅ Directory detection works
- ✅ Object listing works
- ✅ Download preserves structure
- ✅ Cache uses cached_data/{target_location}
- ✅ Anonymous access works with public buckets

Ready for testing!
