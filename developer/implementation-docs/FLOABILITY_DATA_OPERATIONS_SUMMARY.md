# Floability Data Operations & Caching Summary

## Overview
Floability manages data dependencies for distributed workflows through a declarative YAML specification system with built-in content-addressable caching. Data can be sourced from multiple locations (HTTP, S3, Pelican/OSDF, local filesystem, backpack-relative paths) and materialized into workflow instances with integrity verification.

**Latest Updates (Feb 2026)**:
- **S3 Directory Support**: Full support for downloading S3 directories recursively
- **Pelican Directory Support**: Download entire directories from Pelican/OSDF federations
- **New Cache Structure**: Simplified `cached_data/` structure that mirrors target paths
- **Improved Materialization**: Simplified symlink logic for predictable behavior
- **Directory Detection**: Auto-detect directories via trailing slash or metadata

## Core Concepts

### 1. Data Specification (data.yml)
- **Location**: Typically at `<backpack_root>/data/data.yml`
- **Structure**: YAML file containing:
  - `schema_version`: Version identifier (e.g., "1.0")
  - `default_profile`: Name of default profile to use
  - `data_profiles`: Map of profile names to data profiles

### 2. Data Profiles
Each profile contains:
- **`policy`** (optional): Runtime behavior configuration
  - `retry_attempts`: Number of retry attempts for failed downloads
  - `timeout`: Timeout in seconds for download operations
  - `size_tolerance_bytes`: Allowed deviation from expected size
  - `run_operation`: Default operation ("check", "fetch", "verify")
  - `verification_type`: "strict" (requires checksum) or "size_only"

- **`data`** (required): List of data items to manage

### 3. Data Item Schema
Each item in the `data` list can specify:
- **`name`**: Optional identifier for the item
- **`source_type`**: Type of source ("http", "s3", "pelican", "osdf", "fs", "backpack", or "multi")
- **`source`**: Source URI/path (for single source)
- **`sources`**: List of fallback sources (for multi-source items)
- **`source_object_type`**: Optional explicit type ("file" or "directory") - NEW
- **`target_location`** or **`target_path`**: Where to materialize the data (relative to workflow directory)
- **`target_prefix`**: Optional override for target directory prefix
- **`expected_size`**: Expected file size in bytes (for validation)
- **`checksum`**: Expected checksum in format "algorithm:hex" (e.g., "sha256:abc123...")
- **`content_type`**: Optional MIME type
- **`post_process`**: Optional post-processing instructions (not yet implemented)

### 4. Source Types

#### Single File/Directory Sources
- **`http`**: Download from HTTP/HTTPS URL
- **`s3`**: Download from S3 bucket (supports files and directories)
- **`pelican`/`osdf`**: Download from Pelican/OSDF federation (supports files and directories)
- **`fs`**: Local filesystem path (absolute or relative to backpack)
- **`backpack`**: Relative to backpack root directory (e.g., "backpack://data/file.csv")

#### Multi-Source Fallback
- **`multi`**: Multiple fallback sources (tries each until one succeeds)

#### Directory Detection (S3 and Pelican)
Three-tier priority for detecting directories:
1. **Explicit field**: `source_object_type: "directory"` or `source_object_type: "file"`
2. **URL trailing slash**: `s3://bucket/prefix/` or `pelican://server/path/` → directory
3. **Metadata check**: Query S3/Pelican to determine if source is a directory

## Data Operations

### 1. **Check** (Metadata-Only)
- **Command**: `floability data --mode check`
- **Purpose**: Verify data sources exist and match expected metadata without downloading
- **Actions**:
  - Queries remote sources for metadata (size, existence)
  - Validates expected_size within tolerance
  - Reports cache status if caching enabled
  - No file downloads or writes
- **Returns**: Success if all items exist and match expected size

### 2. **Fetch** (Download/Copy)
- **Command**: `floability data --mode fetch`
- **Purpose**: Download/copy data to target locations
- **Actions**:
  - Downloads data from sources to cache (if caching enabled)
  - Materializes data to target locations using specified cache mode
  - For multi-source items, tries each source until success
  - Skips existing targets unless `--force` specified
- **Returns**: Success if all items fetched successfully

### 3. **Verify** (Fetch + Integrity Check)
- **Command**: `floability data --mode verify`
- **Purpose**: Ensure data exists and passes integrity checks
- **Actions**:
  - Performs fetch if target doesn't exist
  - Validates checksums (if specified and verification_type="strict")
  - Validates file sizes within tolerance
  - Produces detailed verification report
- **Returns**: Success if all items exist and pass integrity checks

## Caching System

### Cache Architecture (Updated Feb 2026)

#### Cache Location
- **Base directory**: Specified via `--data-cache-dir` (defaults to `~/floability-data-cache`)
- **Cache root**: `<cache-base-dir>/`
- **Per-artifact**: `<cache-base-dir>/<cache_key>/`

#### Cache Entry Structure (NEW)
```
<cache-base-dir>/
  <cache_key>/              # Deterministic hash of artifact spec (SHA-256)
    cached_data/            # NEW: Stores data with full target_location path
      <target_location>/    # e.g., data/samples/file.root
        <files...>
    .meta.json              # Metadata (artifact spec, SHA-256, size, timestamps)
    .verify.lock            # Temporary lock during build/verify (prevents concurrent writes)
```

**Key Change**: The cache now stores data under `cached_data/<target_location>` instead of `cached_data/data/<basename>`. This preserves the full directory structure and enables predictable materialization.

**Example**:
- **Spec**: `target_location: "data/samples/test"`
- **Cache**: `<cache_key>/cached_data/data/samples/test/file.root`
- **Workflow**: `workflow/data/samples/test/file.root` (symlinked to cache)

#### Cache Key Computation
- Deterministic hash computed from "artifact spec" including:
  - Source(s) with resolved absolute paths for local sources
  - Expected size (if specified)
  - Checksum (if specified)
  - Content type (if specified)
  - Post-process settings (if specified)
- Multi-source items include all sources in order
- Cache key is SHA-256 hex digest (64 chars) of normalized artifact spec JSON

### Materialization Modes
### Materialization Logic (Updated Feb 2026)

The new materialization approach is simpler and more predictable:

1. **Read top-level items** from `cached_data/` (e.g., `data/`)
2. **Find workflow root** by locating where the first item name appears in `target_path`
3. **Create symlinks** from `workflow_root/{item_name}` to `cached_data/{item_name}`

**Example**:
- Cache: `cached_data/data/samples/test/file.root`
- Target path: `/instance/workflow/data/samples/test`
- First item: `data`
- Workflow root: `/instance/workflow` (parent of `data` in target path)
- Symlink: `/instance/workflow/data` → `cached_data/data`

This ensures the entire directory structure is preserved with a single symlink at the top level.

### Cache Operations Flow

#### Building Cache Entry (First Access)
1. Compute cache key from artifact spec
2. Check if cache entry exists and is valid
3. If not valid or `--force-data-cache`:
   - Acquire `.verify.lock` (timeout: 300s)
   - Download/copy data to `<cache_dir>/cached_data/<target_location>/`
   - For S3/Pelican directories: recursively download all files
   - Apply post_process if specified (not yet implemented)
   - Compute content SHA-256 hash and size
   - Write `.meta.json` with metadata
   - Release lock
4. Materialize from cache to workflow using specified mode

#### Using Existing Cache Entry
1. Compute cache key
2. Lookup cache entry:
   - Check cache directory exists
   - Check `.meta.json` exists and is valid
   - Verify artifact spec matches
   - Verify size matches (if expected_size specified)
   - Check `cached_data/` directory exists
3. If valid: materialize from cache to target
4. If invalid: rebuild cache entry

#### Concurrent Access Protection
- `.verify.lock` file prevents duplicate work during concurrent runs
- Lock timeout: 300 seconds
- Falls back to direct fetch if lock timeout occurs

### Cache Metadata (.meta.json)
Contains:
- `artifact_spec`: Normalized spec used to compute cache key
- `content_sha256`: SHA-256 hash of cached content
- `actual_size`: Actual size in bytes
- `created_at_iso`: ISO timestamp of cache entry creation
- `source_fingerprint`: Optional fingerprint for filesystem sources
- For directories: composite hash of all files with sorted paths

### CLI Flags for Caching

- **`--data-cache-mode <mode>`**: Set materialization mode (off|symlink|hardlink|copy)
- **`--force-data-cache`**: Force rebuild of cache entries even if valid
- **`--data-cache-dir <dir>`**: Set cache directory (default: `~/floability-data-cache`)
- **`--data-profile <name>`**: Select which data profile to use

## Integration with Workflow Execution

### `floability run` and `floability instance create`
- Automatically pass `--data-cache-dir`, `--data-cache-mode`, and `--force-data-cache` to data operations
- Execute data operation phase when `--data-spec` provided
- Data materialized into instance workflow directory

### Target Path Resolution
- **Default**: `<instance_dir>/workflow/<target_location>`
- **Override**: Use `target_prefix` in item or `--target-root` CLI flag
- Relative `target_location` paths resolved against target prefix

## Example Data Specifications

### Example 1: HTTP Sources with Checksums

```yaml
schema_version: 1.0
default_profile: gutenberg_data

data_profiles:
  gutenberg_data:
    policy:
      retry_attempts: 3
      timeout: 60
      size_tolerance_bytes: 1024
      run_operation: fetch
      verification_type: strict

    data:
      - name: gatsby
        source_type: http
        source: https://www.gutenberg.org/cache/epub/64317/pg64317.txt
        content_type: text/plain
        expected_size: 306594
        checksum: sha256:e6b7897aa8498b8dac4df0664827f857bc01135c3d9311adb820979bbc44b763
        target_location: data/pg64317.txt

      - name: frankenstein
        source_type: http
        source: https://www.gutenberg.org/files/84/84-0.txt
        content_type: text/plain
        expected_size: 421633
        checksum: sha256:06c37d2c52d208d3d81eb12c3b10b5edbd7728b73554325ddceadbe2fb427e77
        target_location: data/frankenstein.txt
```

### Example 2: S3 Directory Download

```yaml
schema_version: 1.0
default_profile: s3_data

data_profiles:
  s3_data:
    policy:
      retry_attempts: 0
      timeout: 30
      size_tolerance_bytes: 10
      run_operation: fetch
      verification_type: size_only

    data:
      # Explicit directory type
      - name: sample_data
        source_type: s3
        source: s3://floability/reyer_data/
        source_object_type: directory
        target_location: data/samples

      # Auto-detect via trailing slash
      - name: training_data
        source_type: s3
        source: s3://mybucket/datasets/training/
        target_location: data/training

      # Single file
      - name: model_weights
        source_type: s3
        source: s3://mybucket/models/weights.h5
        source_object_type: file
        target_location: data/model.h5
```

### Example 3: Pelican/OSDF Directory Download

```yaml
schema_version: 1.0
default_profile: pelican_data

data_profiles:
  pelican_data:
    policy:
      retry_attempts: 2
      timeout: 60
      run_operation: fetch
      verification_type: size_only

    data:
      # Pelican directory with explicit type
      - name: cms_data
        source_type: pelican
        source: pelican://osg-htc.org:8443/ospool/uc-shared/public/OSG-Staff/validation/test-data/
        source_object_type: directory
        target_location: data/cms

      # Auto-detect via trailing slash
      - name: physics_samples
        source_type: osdf
        source: osdf://ospool/datasets/physics/samples/
        target_location: data/physics_samples
```

### Example 4: Multi-Source Fallback

```yaml
schema_version: 1.0
default_profile: resilient_data

data_profiles:
  resilient_data:
    policy:
      retry_attempts: 2
      timeout: 60
      verification_type: strict

    data:
      - name: dataset
        source_type: multi
        sources:
          # Try Pelican first
          - source_type: pelican
            source: pelican://server.example.org:443/datasets/data.csv
          # Fallback to S3
          - source_type: s3
            source: s3://backup-bucket/datasets/data.csv
          # Final fallback to HTTP
          - source_type: http
            source: https://backup.example.org/datasets/data.csv
          # Last resort: local backpack copy
          - source_type: backpack
            source: data/fallback/data.csv
        expected_size: 1048576
        checksum: sha256:abc123def456...
        target_location: data/dataset.csv
```

### Example 5: Mixed Files and Directories

```yaml
schema_version: 1.0
default_profile: mixed_data

data_profiles:
  mixed_data:
    policy:
      retry_attempts: 0
      timeout: 30
      run_operation: fetch
      verification_type: size_only

    data:
      # Directory from S3
      - name: s3_samples
        source_type: s3
        source: s3://floability/dv5-sample-data/
        source_object_type: directory
        target_location: data/s3_samples

      # Directory from Pelican
      - name: pelican_data
        source_type: pelican
        source: pelican://osg-htc.org:8443/ospool/data/
        source_object_type: directory
        target_location: data/pelican

      # Single file from HTTP
      - name: config
        source_type: http
        source: https://example.org/config.json
        target_location: config/app.json

      # Local file
      - name: readme
        source_type: backpack
        source: README.md
        target_location: docs/README.md
```

## Best Practices

## Best Practices

1. **Use symlink mode** for read-only workflows (default, most efficient)
2. **Use copy mode** if workflow modifies files in-place
3. **Always specify checksums** for production data (enables strict verification)
4. **Use multi-source fallbacks** for reliability across environments
5. **Set appropriate size_tolerance_bytes** to account for metadata variations
6. **Share cache across runs** by using consistent `--data-cache-dir`
7. **Use profiles** to switch between local/remote/development/production sources
8. **Use trailing slashes** for directories (`s3://bucket/dir/`) to avoid ambiguity
9. **Specify source_object_type** explicitly when auto-detection might be unclear
10. **Use descriptive names** for data items to improve logging clarity

## Directory Download Specifics

### S3 Directories
- **Detection**: Trailing `/`, explicit `source_object_type: directory`, or metadata check
- **Features**: 
  - Recursive download preserving structure
  - Resume support for interrupted downloads
  - Progress bars for each file
  - Anonymous access via `AWS_NO_SIGN_REQUEST=true`
- **Example**: `s3://floability/dv5-sample-data/` downloads all objects under that prefix

### Pelican/OSDF Directories
- **Detection**: Trailing `/`, explicit `source_object_type: directory`, or metadata check via `fs.walk()`
- **Features**:
  - Recursive download using PelicanFileSystem
  - Structure preservation
  - Progress tracking
  - SSL bypass mode for testing (DISABLE_SSL=True)
- **Example**: `pelican://osg-htc.org:8443/ospool/data/` downloads all files recursively

### Cache Structure for Directories
- Directories are cached with full path: `cached_data/<target_location>/`
- Example: `target_location: "data/samples"` → `cached_data/data/samples/file1.root`
- Materialization creates symlink at top level: `workflow/data` → `cached_data/data`

## Example Workflow Commands

```bash
# Check data availability (no download)
floability data --data-spec data/data.yml --mode check --verbose

# Fetch data with caching (symlink mode)
floability data --data-spec data/data.yml \
  --mode fetch \
  --data-cache-mode symlink \
  --data-cache-dir ~/floability-data-cache \
  --verbose

# Fetch specific profile
floability data --data-spec data/data.yml \
  --data-profile s3_data \
  --mode fetch \
  --data-cache-mode symlink \
  --verbose

# Force cache rebuild
floability data --data-spec data/data.yml \
  --mode fetch \
  --data-cache-mode symlink \
  --force-data-cache \
  --verbose

# Run workflow with automatic data fetch
floability run --backpack example/cms-physics-lfv \
  --data-spec data/data.yml \
  --data-profile s3_data \
  --data-cache-mode symlink \
  --data-cache-dir ~/floability-data-cache
```

## Testing Directory Downloads

### S3 Test Script
```bash
conda activate floability-env
python scripts/test-s3-dir-download.py
```

Tests:
1. S3 directory detection
2. Object listing
3. Directory download
4. Caching with data handler

### Pelican Test Script
```bash
conda activate floability-env
python scripts/test-pelican-dir-download.py
```

## Troubleshooting

### Common Issues

**Issue**: Double directory nesting (e.g., `workflow/data/samples/samples/`)
- **Cause**: Old cache structure or materialization logic
- **Fix**: Clear cache and re-download with latest code

**Issue**: S3 anonymous access fails
- **Solution**: Set environment variable `export AWS_NO_SIGN_REQUEST=true`

**Issue**: Pelican SSL errors
- **Solution**: For testing only, set `DISABLE_SSL=True` in code

**Issue**: Cache depth calculation incorrect
- **Cause**: Multiple items from different operations in same cache
- **Fix**: Latest code finds leaf directories correctly by examining target_path structure

**Issue**: Permission denied when creating symlinks
- **Solution**: Use `--data-cache-mode copy` instead of symlink

## Implementation Files

Key source files:
- `src/floability/data/data_handler.py`: Core data operations and caching logic
- `src/floability/data/http_file_utils.py`: HTTP download utilities
- `src/floability/data/s3_file_utils.py`: S3 file and directory operations
- `src/floability/data/pelican_file_utils.py`: Pelican/OSDF file and directory operations
- `src/floability/data/fs_file_utils.py`: Filesystem utilities
- `src/floability/ops/data.py`: CLI operation handlers
- `docs/concept/data-caching.md`: User-facing caching documentation
- `docs/reference/data.md`: Complete data specification reference

### New Functions (Feb 2026)
- `s3_directory_download()`: Download entire S3 directories
- `is_s3_directory()`: Detect if S3 URI is a directory
- `s3_list_objects()`: List all objects in S3 prefix
- `pelican_directory_download()`: Download entire Pelican directories
- `is_pelican_directory()`: Detect if Pelican URI is a directory
- `pelican_list_directory()`: List all files in Pelican directory

## Key Implementation Details

- **Content addressing**: Cache keys ensure same data specs share cache entries
- **Atomic cache builds**: Lock mechanism prevents race conditions
- **Multi-source failover**: Automatic fallback to alternative sources
- **Directory support**: Handles both files and directory trees for S3 and Pelican
- **Integrity verification**: SHA-256 checksums for strict validation
- **Flexible materialization**: Choose between symlink/hardlink/copy based on workflow needs
- **Idempotent operations**: Safe to re-run fetch/verify operations
- **Concurrent execution safe**: Lock files prevent cache corruption
- **Predictable structure**: Cached data mirrors target_location exactly
- **Simple materialization**: Top-level symlinks preserve entire directory structure

---

*Last Updated: February 7, 2026*
*For sharing with LLMs or team members to understand Floability's data management system*
