# S3 Support in Floability

Floability now provides first-class support for Amazon S3 data sources using native `s3://` URIs.

## Features

- **Native S3 URIs**: Use `s3://bucket/key` format directly in data specs
- **Automatic detection**: S3 URIs are automatically detected and routed to boto3
- **Metadata operations**: Check file existence and properties without downloading
- **Efficient downloads**: Resume support, progress bars, atomic finalization
- **Cache integration**: Full support for Floability's caching system
- **Directory support**: List and download entire S3 prefixes

## Quick Start

### 1. Install boto3

The S3 support requires boto3:

```bash
# Via conda
conda install -c conda-forge boto3

# Or via pip
pip install boto3
```

### 2. Configure AWS Credentials

Boto3 uses the standard AWS credential chain. Choose one of:

**Environment variables** (recommended for HPC):
```bash
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_DEFAULT_REGION="us-east-1"
```

**AWS credentials file** (`~/.aws/credentials`):
```ini
[default]
aws_access_key_id = your-access-key
aws_secret_access_key = your-secret-key
region = us-east-1
```

**IAM roles** (automatic on AWS EC2/ECS/Lambda).

### 3. Use S3 URIs in Data Specs

Create a data specification with S3 sources:

```yaml
# data/data.yml
items:
  - name: physics-dataset
    source: s3://floability/vbf-zh-hbb_delphes.zip
    size: 3187467820
    checksum: "md5:7e33ecc8fb9e3c6d6f1cf85fd3c34ae4"
```

### 4. Run Floability Operations

```bash
# Check S3 data availability
floability data check --backpack /path/to/backpack

# Fetch S3 data with caching
floability data fetch --backpack /path/to/backpack --cache-mode symlink

# Verify S3 data integrity
floability data verify --backpack /path/to/backpack
```

## Usage Examples

### Single File Download

```yaml
items:
  - name: my-dataset
    source: s3://my-bucket/data/dataset.zip
    size: 1048576
    checksum: "sha256:abc123..."
```

### Multiple Sources with Fallback

```yaml
items:
  - name: important-data
    sources:
      - source: s3://primary-bucket/data.zip
        source_type: s3
      - source: s3://backup-bucket/data.zip
        source_type: s3
      - source: https://backup-server.com/data.zip
        source_type: http
    size: 2097152
```

### Directory/Prefix Download

```yaml
items:
  - name: dataset-collection
    source: s3://my-bucket/datasets/
    # Will download all files under 'datasets/' prefix
```

## Python API

Use S3 utilities directly in Python:

```python
from floability.data.s3_file_utils import (
    parse_s3_uri,
    s3_file_metadata,
    s3_file_download,
    s3_list_objects,
)

# Parse S3 URI
bucket, key = parse_s3_uri("s3://my-bucket/my-file.txt")

# Get file metadata
metadata = s3_file_metadata("s3://my-bucket/my-file.txt")
print(f"Size: {metadata['size']} bytes")
print(f"ETag: {metadata['etag']}")

# Download file
local_path = s3_file_download(
    "s3://my-bucket/my-file.txt",
    dest_dir="/tmp",
    filename="downloaded.txt",
    show_progress=True,
)

# List bucket objects
objects = s3_list_objects("s3://my-bucket/prefix/")
for obj in objects:
    print(f"{obj['key']}: {obj['size']} bytes")
```

## Cache Modes with S3

S3 sources support all Floability cache modes:

- **`off`**: Direct download, no caching
- **`symlink`**: Download to cache, symlink to workspace (default)
- **`hardlink`**: Download to cache, hardlink to workspace
- **`copy`**: Download to cache, copy to workspace

Example:
```bash
floability data fetch --backpack . --cache-mode symlink
```

## Fingerprint Modes

For cache key generation, S3 supports fingerprinting:

- **`meta`**: Uses ETag and Last-Modified from S3 metadata (fast, no download)
- **`sample`**: Downloads first N bytes for fingerprinting
- **`strict`**: Downloads entire file for SHA256 checksum

## Performance Tips

1. **Use metadata checks**: `floability data check` verifies availability without downloading
2. **Enable caching**: Reuse downloaded files across multiple runs
3. **Resume downloads**: Interrupted downloads automatically resume from `.part` files
4. **Region locality**: Use S3 buckets in the same region as your compute for faster transfers
5. **Parallel downloads**: Floability can download multiple S3 files concurrently

## Troubleshooting

### NoCredentialsError

**Problem**: `botocore.exceptions.NoCredentialsError: Unable to locate credentials`

**Solution**: Configure AWS credentials using one of the methods above.

### Access Denied

**Problem**: `botocore.exceptions.ClientError: An error occurred (AccessDenied)`

**Solution**: Verify your AWS credentials have `s3:GetObject` permission for the bucket.

### Network Timeout

**Problem**: Downloads timing out or failing

**Solution**: 
- Increase timeout: Pass `timeout=300` to functions
- Check network connectivity to S3
- Verify bucket region matches your configuration

### Large File Downloads

**Problem**: Large files fail or take too long

**Solution**:
- Use resume feature (automatic with `.part` files)
- Enable progress bar: `show_progress=True`
- Consider using AWS CLI for very large files (>100GB)

## Migrating from HTTP S3 URLs

If you're currently using HTTP URLs for S3 access:

**Before** (HTTP):
```yaml
items:
  - name: data
    source: https://floability.s3.us-east-1.amazonaws.com/file.zip
    source_type: http
```

**After** (Native S3):
```yaml
items:
  - name: data
    source: s3://floability/file.zip
    # source_type automatically detected
```

Benefits of native S3:
- Faster metadata operations (no HTTP overhead)
- Better error handling and retries
- Support for private buckets without signed URLs
- Efficient directory operations
- Native AWS credential integration

## Testing S3 Support

Run S3 tests (requires AWS credentials):

```bash
# Run all S3 tests
pytest tests/test_s3_file_utils.py tests/test_data_handler_s3.py -v

# Or use the helper script
python tests/run_tests.py s3
./tests/run_tests.sh s3
```

Most tests are marked with `@pytest.mark.skip` by default to avoid accidental charges. Remove the skip decorator to run them with valid credentials.

## Implementation Details

- **Module**: `floability/data/s3_file_utils.py`
- **Integration**: `floability/data/data_handler.py`
- **Dependencies**: `boto3`, `botocore`
- **Download strategy**: Chunked streaming with `.part` files for atomic writes
- **Error handling**: Comprehensive boto3 exception handling
- **Progress tracking**: Optional `tqdm` progress bars

## References

- [Boto3 Documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)
- [AWS S3 Documentation](https://docs.aws.amazon.com/s3/)
- [AWS Credential Configuration](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html)
