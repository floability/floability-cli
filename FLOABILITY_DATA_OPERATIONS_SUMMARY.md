# Floability Data Operations & Caching Summary

## Overview
Floability manages data dependencies for distributed workflows through a declarative YAML specification system with built-in content-addressable caching. Data can be sourced from multiple locations (HTTP, Pelican, local filesystem, backpack-relative paths) and materialized into workflow instances with integrity verification.

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
- **`source_type`**: Type of source ("http", "pelican", "fs", "backpack", "osdf", or "multi")
- **`source`**: Source URI/path (for single source)
- **`sources`**: List of fallback sources (for multi-source items)
- **`target_location`** or **`target_path`**: Where to materialize the data (relative to workflow directory)
- **`target_prefix`**: Optional override for target directory prefix
- **`expected_size`**: Expected file size in bytes (for validation)
- **`checksum`**: Expected checksum in format "algorithm:hex" (e.g., "sha256:abc123...")
- **`content_type`**: Optional MIME type
- **`post_process`**: Optional post-processing instructions (not yet implemented)

### 4. Source Types
- **`http`**: Download from HTTP/HTTPS URL
- **`pelican`**: Download from Pelican federation endpoint
- **`fs`**: Local filesystem path (absolute or relative to backpack)
- **`backpack`**: Relative to backpack root directory (e.g., "backpack://data/file.csv")
- **`multi`**: Multiple fallback sources (tries each until one succeeds)

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

### Cache Architecture

#### Cache Location
- **Base directory**: Specified via `--base-dir` (defaults to current directory)
- **Cache root**: `<base-dir>/flo_data_cache/`
- **Per-artifact**: `<base-dir>/flo_data_cache/<cache_key>/`

#### Cache Entry Structure
```
flo_data_cache/
  <cache_key>/           # Deterministic hash of artifact spec
    data/                # Actual cached content (file or directory tree)
      <filename>         # The cached file(s)
    .meta.json           # Metadata (artifact spec, SHA-256, size, timestamps)
    .verify.lock         # Temporary lock during build/verify (prevents concurrent writes)
```

#### Cache Key Computation
- Deterministic hash computed from "artifact spec" including:
  - Source(s) with resolved absolute paths for local sources
  - Expected size (if specified)
  - Checksum (if specified)
  - Content type (if specified)
  - Post-process settings (if specified)
- Multi-source items include all sources in order
- Cache key is SHA-256 hex digest of normalized artifact spec JSON

### Materialization Modes

Data is materialized from cache to target location using one of four modes:

#### 1. **symlink** (Default)
- Creates symbolic link from target to cache
- **Pros**: Fastest, most space-efficient
- **Cons**: Read-only convention (modifying affects cache)
- **Best for**: Read-only workflows

#### 2. **hardlink**
- Creates hard link sharing inode with cache
- **Pros**: Fast, space-efficient, independent directory entry
- **Cons**: Requires same filesystem, files only (not directories)
- **Best for**: When symlinks not supported but same filesystem

#### 3. **copy**
- Copies bytes from cache to target
- **Pros**: Full isolation, can modify files
- **Cons**: Slower, uses more disk space
- **Best for**: Workflows that modify data in-place

#### 4. **off**
- No caching, direct download/copy to target
- **Best for**: One-off operations or when caching not desired

### Cache Operations Flow

#### Building Cache Entry (First Access)
1. Compute cache key from artifact spec
2. Check if cache entry exists and is valid
3. If not valid or `--force-data-cache`:
   - Acquire `.verify.lock` (timeout: 300s)
   - Download/copy data to `<cache_dir>/data/`
   - Apply post_process if specified (not yet implemented)
   - Compute content SHA-256 hash and size
   - Write `.meta.json` with metadata
   - Release lock
4. Materialize from cache to target using specified mode

#### Using Existing Cache Entry
1. Compute cache key
2. Lookup cache entry:
   - Check cache directory exists
   - Check `.meta.json` exists and is valid
   - Verify artifact spec matches
   - Verify size matches (if expected_size specified)
   - Check `data/` directory exists
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
- For directories: composite hash of all files with sorted paths

### CLI Flags for Caching

- **`--data-cache-mode <mode>`**: Set materialization mode (off|symlink|hardlink|copy)
- **`--force-data-cache`**: Force rebuild of cache entries even if valid
- **`--base-dir <dir>`**: Set base directory for cache storage

## Integration with Workflow Execution

### `floability run` and `floability instance create`
- Automatically pass `--base-dir`, `--data-cache-mode`, and `--force-data-cache` to data operations
- Execute data operation phase when `--data-spec` provided
- Data materialized into instance workflow directory

### Target Path Resolution
- **Default**: `<backpack_root>/workflow/<target_location>`
- **Override**: Use `target_prefix` in item or `--target-root` CLI flag
- Relative `target_location` paths resolved against target prefix

## Best Practices

1. **Use symlink mode** for read-only workflows (default, most efficient)
2. **Use copy mode** if workflow modifies files in-place
3. **Always specify checksums** for production data (enables strict verification)
4. **Use multi-source fallbacks** for reliability across environments
5. **Set appropriate size_tolerance_bytes** to account for metadata variations
6. **Share cache across runs** by using consistent `--base-dir`
7. **Use profiles** to switch between local/remote/development/production sources

## Example Workflow

```bash
# Check data availability (no download)
floability data --data-spec example/rag-lite-bm25/data/data.yml --mode check --verbose

# Fetch data with caching (symlink mode)
floability data --data-spec example/rag-lite-bm25/data/data.yml \
  --mode fetch \
  --data-cache-mode symlink \
  --base-dir /shared/cache \
  --verbose

# Verify data integrity with forced cache rebuild
floability data --data-spec example/rag-lite-bm25/data/data.yml \
  --mode verify \
  --data-cache-mode symlink \
  --force-data-cache \
  --verbose

# Run workflow with automatic data fetch
floability run --backpack example/rag-lite-bm25 \
  --data-spec example/rag-lite-bm25/data/data.yml \
  --data-cache-mode symlink \
  --base-dir /shared/cache
```

## Example Data Specification

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

  backpack_data:
    policy:
      retry_attempts: 0
      timeout: 30
      size_tolerance_bytes: 10
      run_operation: verify
      verification_type: strict

    data:
      - name: gatsby
        source_type: backpack
        source: data/sources/pg64317.txt
        expected_size: 306594
        checksum: sha256:e6b7897aa8498b8dac4df0664827f857bc01135c3d9311adb820979bbc44b763
        target_location: data/pg64317.txt

  multi_source_example:
    policy:
      retry_attempts: 2
      timeout: 60
      verification_type: strict

    data:
      - name: dataset
        sources:
          - source_type: pelican
            source: pelican://server.example.org:443/datasets/data.csv
          - source_type: http
            source: https://backup.example.org/datasets/data.csv
          - source_type: backpack
            source: data/fallback/data.csv
        expected_size: 1048576
        checksum: sha256:abc123def456...
        target_location: data/dataset.csv
```

## Key Implementation Details

- **Content addressing**: Cache keys ensure same data specs share cache entries
- **Atomic cache builds**: Lock mechanism prevents race conditions
- **Multi-source failover**: Automatic fallback to alternative sources
- **Directory support**: Handles both files and directory trees
- **Integrity verification**: SHA-256 checksums for strict validation
- **Flexible materialization**: Choose between symlink/hardlink/copy based on workflow needs
- **Idempotent operations**: Safe to re-run fetch/verify operations
- **Concurrent execution safe**: Lock files prevent cache corruption

## Implementation Files

Key source files:
- `floability/data/data_handler.py`: Core data operations and caching logic
- `floability/data/http_file_utils.py`: HTTP download utilities
- `floability/data/pelican_file_utils.py`: Pelican federation utilities
- `floability/data/fs_file_utils.py`: Filesystem utilities
- `floability/ops/data.py`: CLI operation handlers
- `docs/concept/data-caching.md`: User-facing caching documentation
- `docs/reference/data.md`: Complete data specification reference

---

*Created: January 17, 2026*
*For sharing with LLMs or team members to understand Floability's data management system*
