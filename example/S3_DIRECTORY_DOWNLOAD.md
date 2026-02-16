# S3 Directory Download Support

This document describes S3 directory download support in Floability CLI.

## Overview

Floability now supports downloading entire S3 directories (prefixes) recursively, similar to the Pelican directory download feature.

## Features

- **Directory Detection**: Automatically detects if an S3 URI points to a directory
- **Recursive Download**: Downloads all files in a directory preserving structure
- **Caching**: Supports caching of S3 directories
- **Anonymous Access**: Works with public S3 buckets without credentials

## Usage

### Data Spec Format

```yaml
- name: my_s3_data
  target_location: data/samples
  source: s3://bucket/path/to/directory/
  source_type: s3
  source_object_type: directory  # Optional, auto-detects if omitted
```

### Directory Detection

Three methods (in priority order):

1. **Explicit field**: `source_object_type: directory`
2. **Trailing slash**: URL ends with `/` → directory
3. **Metadata check**: Queries S3 to check if multiple objects exist with the prefix

### Examples

#### Explicit Directory Type
```yaml
- name: dv5_data
  target_location: data/dv5
  source: s3://floability/dv5-sample-data/
  source_type: s3
  source_object_type: directory
```

#### Auto-detect via Trailing Slash
```yaml
- name: samples
  target_location: data/samples
  source: s3://mybucket/samples/
  source_type: s3
```

#### Single File (for comparison)
```yaml
- name: single_file
  target_location: data/file.root
  source: s3://mybucket/file.root
  source_type: s3
  source_object_type: file
```

## Cache Structure

S3 directories are cached under the `cached_data` directory with the full target_location path:

```
cache/
├── cached_data/
│   └── data/
│       └── dv5/
│           ├── file1.root
│           ├── file2.root
│           └── subdir/
│               └── file3.root
└── .meta.json
```

## Access Configuration

### Anonymous Access (Public Buckets)

Set environment variable:
```bash
export AWS_NO_SIGN_REQUEST=true
```

Or in Python:
```python
from floability.data.s3_file_utils import s3_directory_download

s3_directory_download(
    "s3://public-bucket/data/",
    dest_dir="/tmp/data",
    anonymous=True
)
```

### Authenticated Access

Use standard AWS credential chain:
- Environment variables: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- AWS credentials file: `~/.aws/credentials`
- IAM role (for EC2/ECS instances)

## Testing

Test script: `scripts/test-s3-dir-download.py`

```bash
conda activate floability-env
python scripts/test-s3-dir-download.py
```

Test URL: `s3://floability/dv5-sample-data/`

## API Functions

### `is_s3_directory(uri, anonymous=None)`
Check if S3 URI is a directory.

### `s3_list_objects(uri, recursive=True, anonymous=None)`
List all objects in an S3 prefix.

### `s3_directory_download(uri, dest_dir, ...)`
Download entire S3 directory recursively.

## Implementation Details

- Uses `boto3.client('s3').list_objects_v2()` with pagination
- Downloads files in sequence (not parallel)
- Preserves directory structure by default
- Supports resume and overwrite options
- Uses `.part` files for atomic downloads

## Limitations

- No parallel downloads (sequential only)
- No bandwidth limiting
- Requires `boto3` package

## See Also

- [Pelican Directory Downloads](../docs/concept/data-caching.md)
- [Data Spec Format](../docs/reference/data.md)
- [Example Specs](s3-directory-examples.yml)
