# Data Handling in Floability: Implementation Details for Paper

*Generated for paper on portable execution of data-intensive notebook workflows*  
*Date: February 8, 2026*

---

## Table of Contents

1. [Declarative Data Specification](#section-3-declarative-data-specification)
   - [Core Design Principles](#core-design-principles)
   - [Data.yml Structure](#datayml-structure)
   - [Portability Features](#portability-features)
   - [Source Type Abstraction](#source-type-abstraction)
   - [Multi-Source Fallback](#multi-source-fallback)
   - [Profile-Based Configuration](#profile-based-configuration)
   
2. [Implementation in Floability](#section-4-implementation-in-floability)
   - [Three Core Operations](#three-core-operations)
   - [Local Data Cache Architecture](#local-data-cache-architecture)
   - [Content-Addressable Caching](#content-addressable-caching)
   - [Source Fingerprinting](#source-fingerprinting)
   - [Directory vs Single File Handling](#directory-vs-single-file-handling)
   - [Cache Materialization](#cache-materialization)

---

## Section 3: Declarative Data Specification

### Core Design Principles

The Floability data specification is designed around three key principles that enable portable execution:

1. **Separation of Concerns**: Data requirements are specified independently from notebook code
2. **Location Independence**: Data sources are referenced by URI, not filesystem paths
3. **Declarative Configuration**: What data is needed, not how to fetch it

This design allows the same notebook workflow to access data from different locations across HPC sites without modifying the notebook code itself.

### Data.yml Structure

Data requirements are expressed in a YAML file (`data.yml`) typically located at `<backpack_root>/data/data.yml`. The specification follows a hierarchical structure:

```yaml
schema_version: 1.0
default_profile: profile_name

data_profiles:
  profile_name:
    policy:
      retry_attempts: 3
      timeout: 60
      size_tolerance_bytes: 1024
      run_operation: fetch
      verification_type: strict
    
    data:
      - name: dataset_name
        source_type: s3
        source: s3://bucket/path/data.root
        target_location: data/samples/dataset.root
        expected_size: 1048576
        checksum: sha256:abc123...
```

**Key Components:**

1. **Schema Version**: Enables forward compatibility as the spec evolves
2. **Data Profiles**: Named configurations for different execution environments
3. **Policy**: Runtime behavior (retries, timeouts, validation rules)
4. **Data Items**: Individual datasets with source, target, and integrity information

### Portability Features

#### 1. Profile-Based Configuration

Multiple profiles enable environment-specific configurations within a single specification:

```yaml
data_profiles:
  # Development: local filesystem
  local_dev:
    data:
      - source_type: fs
        source: /local/path/to/data.root
        target_location: data/samples/dataset.root
  
  # HPC Site A: S3 access
  hpc_site_a:
    data:
      - source_type: s3
        source: s3://site-a-bucket/data.root
        target_location: data/samples/dataset.root
  
  # HPC Site B: Pelican federation
  hpc_site_b:
    data:
      - source_type: pelican
        source: pelican://osg-htc.org:8443/ospool/data.root
        target_location: data/samples/dataset.root
```

**Portability Benefit**: The same backpack can be executed across different sites by selecting the appropriate profile via `--data-profile` flag. The notebook code remains unchanged because `target_location` is consistent across profiles.

**Implementation**: Profile selection happens during spec loading:
- Default profile is used unless `--data-profile` explicitly specified
- Profile validation ensures required fields are present
- Normalization applies defaults and infers missing fields

#### 2. Target Location Consistency

All profiles specify the same `target_location`, ensuring notebooks can reference data at predictable paths:

```python
# Notebook code - works across all profiles
data_path = Path("data/samples/dataset.root")
df = load_data(data_path)
```

This path-based consistency is critical for portability:
- Notebooks don't need to know about source URIs
- Data appears at the same location regardless of where it came from
- File paths in notebooks are relative to the workflow directory

### Source Type Abstraction

Floability abstracts heterogeneous storage systems through a unified source type system:

| Source Type | Protocol | Use Case | Example |
|------------|----------|----------|---------|
| `http` | HTTP/HTTPS | Public datasets, web-hosted files | `https://data.gov/dataset.csv` |
| `s3` | AWS S3 | Object storage (files & directories) | `s3://bucket/path/data.root` |
| `pelican`/`osdf` | Pelican/OSDF | Federated data systems (files & directories) | `pelican://osg-htc.org:8443/ospool/data/` |
| `fs` | Local filesystem | Site-local storage | `/scratch/shared/data.root` |
| `backpack` | Relative to backpack root | Packaged datasets | `backpack://data/sample.csv` |
| `multi` | Multiple fallback sources | Resilient access | (see below) |

**Automatic Type Inference**: Source types can be inferred from URI schemes:
```yaml
# Explicit (recommended)
- source_type: s3
  source: s3://bucket/data.root

# Inferred (convenience)
- source: s3://bucket/data.root  # type inferred as "s3"
```

**Implementation Details**:
- Type inference occurs during spec normalization (`_normalize_data_item`)
- Backpack-relative paths are resolved against `backpack_root`
- Relative filesystem paths are resolved against `backpack_root` unless absolute

### Multi-Source Fallback

The `multi` source type enables resilient data access across heterogeneous environments:

```yaml
data:
  - name: cms_physics_data
    source_type: multi
    sources:
      # Try Pelican federation first (fastest for HPC sites)
      - source_type: pelican
        source: pelican://osg-htc.org:8443/ospool/cms/data.root
      
      # Fallback to S3 (works everywhere with internet)
      - source_type: s3
        source: s3://cms-open-data/2012/data.root
      
      # Final fallback to HTTP mirror
      - source_type: http
        source: https://cms-mirror.cern.ch/data.root
      
      # Last resort: packaged copy
      - source_type: backpack
        source: data/fallback/data.root
    
    target_location: data/cms/data.root
    expected_size: 108000000  # ~108 GB
    checksum: sha256:def456...
```

**Fallback Logic**:
1. Sources are tried in order until one succeeds
2. Metadata checks (if available) are performed first
3. Download only happens if metadata check passes or is unavailable
4. First successful source is used; remaining sources are skipped

**Portability Benefit**: 
- Workflows can adapt to different network topologies
- No manual configuration needed per site
- Automatic failover if primary source unavailable

**Implementation** (from `_fetch_single_item` and `_download_to_cache`):
```python
if stype == "multi":
    success = False
    for src_entry in item.get("sources", []):
        if _download_to_cache(src_entry, cache_file, backpack_root, verbose):
            success = True
            break  # First success stops iteration
```

### Profile-Based Configuration

Profiles enable environment-specific behavior without changing notebook code:

#### Policy Configuration

Runtime behavior is controlled through policy settings:

```yaml
data_profiles:
  production:
    policy:
      # Retry failed downloads (network resilience)
      retry_attempts: 3
      
      # Timeout for download operations (seconds)
      timeout: 120
      
      # Allow size deviation (handles metadata variations)
      size_tolerance_bytes: 10
      
      # Default operation: 'check', 'fetch', or 'verify'
      run_operation: fetch
      
      # Verification: 'strict' (requires checksum) or 'size_only'
      verification_type: strict
```

**Default Values** (applied during normalization):
- `retry_attempts: 0` (no retries by default)
- `timeout: None` (no timeout)
- `size_tolerance_bytes: 0` (exact size match required)
- `run_operation: 'fetch'` (download by default)
- `verification_type: 'size_only'` (checksums optional)

#### Profile Selection Workflow

1. **Load YAML**: Parse `data.yml` file
2. **Select Profile**: Use `--data-profile` flag or `default_profile` from spec
3. **Validate**: Check required fields (data items, sources, targets)
4. **Normalize**: Apply defaults, infer types, resolve paths
5. **Execute**: Run selected operation with normalized profile

**Implementation** (`load_and_validate_spec`):
```python
def load_and_validate_spec(data_spec, backpack_root, requested_profile, verbose):
    raw = _load_yaml(spec_path)
    profile_name, profile, _ = _select_profile(raw, requested_profile)
    _validate_required_fields(profile)
    normalized = _normalize_data_profile(profile, backpack_root)
    return profile_name, normalized
```

### Data Item Schema

Each data item in the `data` list supports the following fields:

**Required Fields**:
- `source` or `sources`: Where to fetch data from
- `target_location`: Where to materialize data in workflow

**Optional Fields**:
- `name`: Human-readable identifier (default: basename of target_location)
- `source_type`: Type of source (inferred if omitted)
- `source_object_type`: Explicit "file" or "directory" (for S3/Pelican)
- `expected_size`: Size in bytes (used for validation)
- `checksum`: Integrity check in format "algorithm:hex"
- `content_type`: MIME type (informational)
- `post_process`: Transformation commands (not yet implemented)

**Integrity Signals**:
```yaml
# Size validation with tolerance
expected_size: 1048576
policy:
  size_tolerance_bytes: 10  # Allow ±10 bytes

# Checksum validation (strict)
checksum: sha256:e6b7897aa8498b8dac4df0664827f857bc01135c3d9311adb820979bbc44b763

# Algorithm-prefixed checksum (recommended)
checksum: sha256:abc123...
checksum: md5:def456...
checksum: sha1:789abc...
```

**Checksum Inference**: If algorithm not specified, Floability infers from hex length:
- 32 hex chars → MD5
- 40 hex chars → SHA1
- 64 hex chars → SHA256

### Directory Support (New in Feb 2026)

Both S3 and Pelican sources support directory downloads:

```yaml
# Explicit directory type (recommended)
- name: training_data
  source_type: s3
  source: s3://mybucket/datasets/training/
  source_object_type: directory
  target_location: data/training

# Auto-detect via trailing slash
- name: training_data
  source: s3://mybucket/datasets/training/  # trailing "/" signals directory
  target_location: data/training

# Single file for comparison
- name: model_weights
  source: s3://mybucket/models/weights.h5
  source_object_type: file  # explicit file type
  target_location: data/model.h5
```

**Directory Detection Priority**:
1. **Explicit field**: `source_object_type: "directory"` or `"file"`
2. **URL trailing slash**: `s3://bucket/prefix/` → directory
3. **Metadata check**: Query S3/Pelican to determine type

**Implementation** (from `_download_to_cache`):
```python
# Determine if source is a directory
source_obj_type = item.get("source_object_type", "").lower()

is_dir = False
if source_obj_type == "directory":
    is_dir = True
elif source_obj_type == "file":
    is_dir = False
else:
    # Auto-detect: trailing slash or metadata check
    is_dir = source.endswith('/') or is_s3_directory(source)

if is_dir:
    s3_directory_download(source, dest_dir=str(cache_file), ...)
else:
    s3_file_download(source, dest_dir=str(cache_file.parent), ...)
```

---

## Section 4: Implementation in Floability

### Three Core Operations

Floability provides three data operations, each serving different use cases in portable execution:

#### 1. Check (Metadata-Only)

**Purpose**: Verify data availability without downloading

**Use Cases**:
- Pre-flight validation before workflow execution
- Checking cache status without triggering downloads
- Verifying data sources are accessible from current site

**Behavior**:
1. Query source metadata (HEAD requests, S3 head_object, etc.)
2. Validate expected_size within tolerance if specified
3. Report cache status if caching enabled
4. **No downloads or file writes**

**Command**:
```bash
floability data --data-spec data/data.yml --mode check --verbose
```

**Implementation** (`check_data_from_spec`):
```python
def check_data_from_spec(data_spec, backpack_root, ...):
    profile_name, profile = load_and_validate_spec(...)
    items = profile.get("data", [])
    policy = profile.get("policy", {})
    tolerance = policy.get("size_tolerance_bytes", 0)
    
    results = []
    for item in items:
        result = _check_single_item(item, tolerance, backpack_root, ...)
        results.append(result)
    
    success = _print_check_summary(results)
    return success
```

**Metadata Gathering** (per source type):
```python
def _metadata_for_source(item, backpack_root):
    stype = item.get("source_type")
    src = item.get("source")
    
    if stype == "http":
        return http_file_metadata(src)  # HEAD request
    elif stype == "s3":
        return s3_file_metadata(src)    # head_object
    elif stype == "pelican":
        return pelican_file_metadata(src)  # fs.info()
    elif stype in ("fs", "backpack"):
        path = resolve_path(src, backpack_root)
        return fs_file_metadata(str(path))  # stat()
```

**Multi-Source Checking**:
```python
if stype == "multi":
    sources = item.get("sources", [])
    for s in sources:
        meta = _metadata_for_source(s, backpack_root)
        if meta.get("exists"):
            break  # First available source
```

**Size Validation**:
```python
expected_size = item.get("expected_size")
actual_size = meta.get("size")

if expected_size and actual_size:
    diff = abs(actual_size - expected_size)
    size_ok = diff <= tolerance
```

**Output**:
```
[data:check] Summary:
name                exists  size_ok  expected_size  actual_size  cache_exists  cache_valid
cms_data            True    True     108000000      108000123    True          True
training_set        True    False    50000000       50005000     False         N/A
model_weights       False   N/A      1048576        N/A          N/A           N/A
```

#### 2. Fetch (Download/Copy)

**Purpose**: Download/copy data to target locations

**Use Cases**:
- Initial workflow setup (staging data before execution)
- Populating workflow instances with required datasets
- Standard case for most workflow executions

**Behavior**:
1. Check if target already exists (skip if present unless `--force`)
2. Download/copy from source to cache (if caching enabled)
3. Materialize from cache to target location using specified mode
4. For multi-source items, try each source until success

**Command**:
```bash
floability data --data-spec data/data.yml \
  --mode fetch \
  --data-cache-mode symlink \
  --data-cache-dir ~/floability-data-cache \
  --force  # Force re-download even if target exists
```

**Implementation** (`fetch_data_from_spec`):
```python
def fetch_data_from_spec(data_spec, backpack_root, force=False, ...):
    profile_name, profile = load_and_validate_spec(...)
    items = profile.get("data", [])
    
    # Determine target_prefix (where to materialize data)
    if target_root:
        target_prefix = target_root
    elif backpack_root:
        target_prefix = backpack_root / "workflow"
    
    for item in items:
        result = _fetch_single_item(
            item, backpack_root, target_prefix,
            force=force, data_cache_mode=data_cache_mode, ...
        )
```

**Fetch Flow** (with caching):
```python
def _fetch_single_item(item, backpack_root, target_prefix, ...):
    # 1. Resolve target path
    target_path = _resolve_target_path(item, backpack_root, target_prefix)
    
    # 2. Skip if exists (unless force)
    if target_path.exists() and not force:
        return success
    
    # 3. Try cache if enabled
    if data_cache_mode != "off":
        artifact_spec = _create_artifact_spec(item, backpack_root)
        cache_key = _compute_cache_key(artifact_spec)
        cache_dir = _get_cache_dir(cache_base_dir, cache_key)
        
        # Check existing cache
        cache_meta = _lookup_cache_entry(cache_dir, artifact_spec, ...)
        
        if not cache_meta or force_data_cache:
            # Build new cache entry
            if not _acquire_cache_lock(cache_dir, timeout=300):
                # Lock timeout, fall back to direct fetch
                return _attempt_fetch_source(item, target_path, ...)
            
            try:
                success = _build_cache_entry(item, cache_dir, backpack_root, ...)
            finally:
                _release_cache_lock(cache_dir)
        
        # Materialize from cache to target
        return _materialize_from_cache(cache_dir, target_path, mode=data_cache_mode)
    
    # 4. Direct fetch (no caching)
    return _attempt_fetch_source(item, target_path, backpack_root, ...)
```

**Direct Fetch** (no caching):
```python
def _attempt_fetch_source(item, target_path, backpack_root, ...):
    stype = item.get("source_type")
    source = item.get("source")
    
    if stype == "http":
        http_file_download(source, dest_dir=target_path.parent, ...)
    elif stype == "s3":
        # Check if directory or file
        is_dir = is_s3_directory(source) or source.endswith('/')
        if is_dir:
            s3_directory_download(source, dest_dir=target_path, ...)
        else:
            s3_file_download(source, dest_dir=target_path.parent, ...)
    # ... similar for pelican, fs, backpack
```

#### 3. Verify (Fetch + Integrity Check)

**Purpose**: Ensure data exists and passes integrity checks

**Use Cases**:
- Production workflows requiring data integrity guarantees
- Validating checksums of critical datasets
- Ensuring reproducibility through cryptographic verification

**Behavior**:
1. Perform fetch if target doesn't exist
2. Validate size within tolerance (if expected_size specified)
3. Validate checksum (if specified and verification_type="strict")
4. Produce detailed verification report

**Command**:
```bash
floability data --data-spec data/data.yml \
  --mode verify \
  --data-cache-mode symlink \
  --verbose
```

**Implementation** (`verify_data_from_spec`):
```python
def verify_data_from_spec(data_spec, backpack_root, ...):
    profile_name, profile = load_and_validate_spec(...)
    items = profile.get("data", [])
    policy = profile.get("policy", {})
    tolerance = policy.get("size_tolerance_bytes", 0)
    
    results = []
    for item in items:
        # 1. Ensure data exists (fetch if needed)
        target_path = _resolve_target_path(item, backpack_root, target_prefix)
        if not target_path.exists():
            _fetch_single_item(item, backpack_root, target_prefix, ...)
        
        # 2. Size validation
        size_ok = None
        if item.get("expected_size"):
            actual_size = get_file_size(target_path)
            diff = abs(actual_size - expected_size)
            size_ok = diff <= tolerance
        
        # 3. Checksum validation (if strict)
        checksum_ok = None
        if policy.get("verification_type") == "strict":
            checksum_spec = _extract_checksum_field(item)
            if checksum_spec:
                alg, expected_hex = _parse_checksum_spec(checksum_spec)
                actual_hex = _compute_checksum(target_path, alg)
                checksum_ok = (actual_hex == expected_hex)
        
        results.append({
            "name": item.get("name"),
            "exists": target_path.exists(),
            "size_ok": size_ok,
            "checksum_ok": checksum_ok,
            ...
        })
    
    success = _print_verify_summary(results)
    return success
```

**Checksum Computation**:
```python
def _compute_checksum(path, alg, chunk_size=1024*1024):
    h = hashlib.new(alg)  # 'md5', 'sha1', 'sha256', etc.
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
```

**Output**:
```
[data:verify] Summary:
name          exists  size_ok  checksum_ok  expected_size  actual_size  checksum_alg
cms_data      True    True     True         108000000      108000000    sha256
training_set  True    True     False        50000000       50000000     sha256
model         True    False    N/A          1048576        1050000      N/A

❌ Verification failed: 2 items failed checks
```

### Local Data Cache Architecture

The local data cache is a critical component for portable execution across HPC sites. It addresses several challenges:

1. **Avoid Redundant Transfers**: Cache data across multiple workflow runs
2. **Share Data**: Multiple instances can reference the same cached data
3. **Decouple Source from Target**: Source changes don't affect workflow paths
4. **Enable Materialization Modes**: Support symlink/hardlink/copy strategies

#### Cache Directory Structure

**Cache Root**: `<cache-base-dir>/` (default: `~/floability-data-cache`)

**Per-Artifact Structure** (Updated Feb 2026):
```
<cache-base-dir>/
  <cache_key>/                    # SHA-256 of artifact spec (64 hex chars)
    cached_data/                  # NEW: Full target structure preserved
      <target_location>/          # e.g., "data/samples/file.root"
        <files...>
    .meta.json                    # Metadata (artifact spec, hashes, timestamps)
    .verify.lock                  # Temporary lock during cache build
```

**Key Design Change (Feb 2026)**: 
- **Old**: `cached_data/data/<basename>` (flat structure)
- **New**: `cached_data/<target_location>` (full path structure)
- **Benefit**: Simplifies materialization, handles nested directories naturally

**Example**:
```
# Data item spec
target_location: "data/samples/test/file.root"

# Old cache structure
<cache_key>/
  cached_data/
    data/
      file.root  # Lost "samples/test" structure

# New cache structure (Feb 2026)
<cache_key>/
  cached_data/
    data/
      samples/
        test/
          file.root  # Full structure preserved
```

#### Cache Key Computation (Content-Addressable)

Cache keys are computed from a normalized "artifact spec" containing only fields that affect the cached bytes:

**Artifact Spec Fields**:
- `source_type`: Type of source
- `source` or `sources`: Source URI(s) with resolved absolute paths for local sources
- `checksum`: Expected checksum (if specified)
- `expected_size`: Expected size (if specified)
- `content_type`: MIME type (if specified)
- `post_process`: Transformation instructions (if specified)

**NOT included** (target-specific):
- `name`: Display name
- `target_location`: Where to materialize
- `target_prefix`: Target directory

**Implementation** (`_create_artifact_spec`):
```python
def _create_artifact_spec(item, backpack_root):
    artifact = {}
    artifact["source_type"] = item.get("source_type")
    
    if item["source_type"] == "multi":
        # Include all sources in order
        sources = []
        for s in item.get("sources", []):
            s_type = s.get("source_type")
            s_source = s.get("source")
            # Resolve relative fs/backpack paths to absolute
            if s_type in ("fs", "backpack"):
                p = Path(s_source)
                if not p.is_absolute():
                    s_source = str((backpack_root / p).resolve())
            sources.append({"source_type": s_type, "source": s_source})
        artifact["sources"] = sources
    else:
        source = item.get("source")
        # Resolve relative paths to absolute
        if item["source_type"] in ("fs", "backpack"):
            p = Path(source)
            if not p.is_absolute():
                source = str((backpack_root / p).resolve())
        artifact["source"] = source
    
    # Optional fields (only if specified)
    if item.get("checksum"):
        artifact["checksum"] = item["checksum"]
    if item.get("expected_size"):
        artifact["expected_size"] = item["expected_size"]
    if item.get("content_type"):
        artifact["content_type"] = item["content_type"]
    if item.get("post_process"):
        artifact["post_process"] = item["post_process"]
    
    return artifact
```

**Cache Key Computation** (`_compute_cache_key`):
```python
def _compute_cache_key(artifact_spec):
    # Canonical JSON (sorted keys, compact)
    canonical_json = json.dumps(artifact_spec, sort_keys=True, separators=(",", ":"))
    
    # SHA-256 hash
    cache_key = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    
    return cache_key  # 64 hex characters
```

**Content-Addressable Benefits**:
1. **Deduplication**: Same source → same cache entry
2. **Deterministic**: Same artifact spec → same cache key
3. **Safe Sharing**: Multiple workflows can safely share cache entries
4. **Integrity**: Cache key depends on checksums/sizes if specified

**Example**:
```python
# Two data items with same source but different targets
item1 = {
    "source_type": "s3",
    "source": "s3://bucket/data.root",
    "target_location": "data/run1/data.root",
    "checksum": "sha256:abc123..."
}

item2 = {
    "source_type": "s3",
    "source": "s3://bucket/data.root",
    "target_location": "data/run2/data.root",  # Different target
    "checksum": "sha256:abc123..."
}

# Both produce SAME cache key (target_location not in artifact spec)
# -> Both use same cache entry, but materialize to different locations
```

### Content-Addressable Caching

#### Building Cache Entries

**Cache Build Flow** (`_build_cache_entry`):
```python
def _build_cache_entry(item, cache_dir, backpack_root, fingerprint_mode, ...):
    # 1. Create cached_data/ directory
    cached_data_dir = cache_dir / "cached_data"
    cached_data_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. Determine cache file path with full target_location structure
    target_location = item.get("target_location")
    cache_file = cached_data_dir / target_location  # e.g., "data/samples/test/file.root"
    
    # 3. Download/copy data to cache
    stype = item.get("source_type")
    if stype == "multi":
        # Try each source until success
        for src_entry in item.get("sources", []):
            if _download_to_cache(src_entry, cache_file, backpack_root, ...):
                break
    else:
        _download_to_cache(item, cache_file, backpack_root, ...)
    
    # 4. Apply post-processing (not yet implemented)
    post_process = item.get("post_process")
    if post_process:
        # TODO: unzip, untar, transform, etc.
        pass
    
    # 5. Compute content hash and size
    content_sha256, actual_size = _compute_content_hash(cache_file)
    
    # 6. Compute source fingerprint (for filesystem sources)
    source_fingerprint = None
    if stype in ("fs", "backpack"):
        from .fingerprint import compute_fingerprint
        source_path = resolve_path(item["source"], backpack_root)
        source_fingerprint = compute_fingerprint(
            str(source_path),
            mode=fingerprint_mode,  # "meta", "sample", or "strict"
            verbose=verbose
        )
    
    # 7. Write metadata
    artifact_spec = _create_artifact_spec(item, backpack_root)
    _write_cache_metadata(
        cache_dir, artifact_spec, content_sha256, actual_size, source_fingerprint
    )
    
    return True
```

#### Content Hash Computation

Content hashing differs for files vs directories:

**Single Files** (`_compute_content_hash`):
```python
def _compute_content_hash(path):
    if path.is_file():
        h = hashlib.sha256()
        size = 0
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
        return h.hexdigest(), size
```

**Directories** (Merkle-like tree hash):
```python
elif path.is_dir():
    h = hashlib.sha256()
    total_size = 0
    
    # Collect all files with their hashes
    file_hashes = []
    for root, dirs, files in os.walk(path):
        dirs.sort()   # Deterministic order
        files.sort()
        
        for filename in files:
            file_path = Path(root) / filename
            rel_path = file_path.relative_to(path)
            file_hash, file_size = _compute_content_hash(file_path)  # Recursive
            file_hashes.append((str(rel_path), file_hash, file_size))
            total_size += file_size
    
    # Hash sorted list of (path, hash, size)
    for rel_path, file_hash, file_size in sorted(file_hashes):
        h.update(f"{rel_path}:{file_hash}:{file_size}\n".encode("utf-8"))
    
    return h.hexdigest(), total_size
```

**Directory Hash Properties**:
- **Structure-sensitive**: Different file arrangements produce different hashes
- **Deterministic**: Same directory tree → same hash (files sorted)
- **Content-addressed**: Hash depends on file contents, not just metadata
- **Efficient**: Only hashes file paths and individual file hashes (not re-reading content)

#### Cache Metadata (.meta.json)

Metadata stored in `.meta.json`:

```json
{
  "artifact_spec": {
    "source_type": "s3",
    "source": "s3://bucket/data.root",
    "checksum": "sha256:abc123...",
    "expected_size": 108000000
  },
  "content_sha256": "def456...",
  "actual_size": 108000123,
  "created_at": 1707350400.0,
  "created_at_iso": "2026-02-08T00:00:00Z",
  "source_fingerprint": "789abc...",
  "fingerprint_mode": "meta",
  "fingerprint_params": {
    "size": 108000123,
    "mtime_ns": 1707350400000000000
  }
}
```

**Fields**:
- `artifact_spec`: Original spec used to compute cache key
- `content_sha256`: Hash of cached content (file or directory tree)
- `actual_size`: Actual size of cached content
- `created_at*`: Timestamps
- `source_fingerprint`: Fingerprint of original source (fs/backpack only)
- `fingerprint_mode`: Mode used ("meta", "sample", "strict")
- `fingerprint_params`: Mode-specific parameters

#### Cache Lookup and Validation

**Lookup Flow** (`_lookup_cache_entry`):
```python
def _lookup_cache_entry(cache_dir, artifact_spec, fingerprint_mode, backpack_root, ...):
    # 1. Check cache directory exists
    if not cache_dir.exists():
        return None  # Cache miss
    
    # 2. Check for lock file (build in progress)
    lock_file = cache_dir / ".verify.lock"
    if lock_file.exists():
        return None  # Cache building
    
    # 3. Read metadata
    meta = _read_cache_metadata(cache_dir)
    if not meta:
        return None  # Invalid/missing metadata
    
    # 4. Verify artifact spec matches
    cached_spec = meta.get("artifact_spec", {})
    if cached_spec != artifact_spec:
        return None  # Spec mismatch
    
    # 5. Check cached_data/ directory exists
    cached_data_dir = cache_dir / "cached_data"
    if not cached_data_dir.exists():
        return None  # Data missing
    
    # 6. Validate size (if specified)
    expected_size = artifact_spec.get("expected_size")
    actual_size = meta.get("actual_size")
    if expected_size and actual_size and expected_size != actual_size:
        return None  # Size mismatch
    
    # 7. Validate source fingerprint (for fs/backpack sources)
    source_type = artifact_spec.get("source_type")
    if source_type in ("fs", "backpack"):
        cached_fingerprint = meta.get("source_fingerprint")
        if not cached_fingerprint:
            return None  # Old cache format (no fingerprint)
        
        # Recompute fingerprint from current source
        source = artifact_spec.get("source")
        source_path = resolve_path(source, backpack_root)
        
        if not source_path.exists():
            return None  # Source no longer exists
        
        from .fingerprint import compute_fingerprint
        current_fingerprint = compute_fingerprint(
            str(source_path),
            mode=fingerprint_mode,
            verbose=False
        )
        
        if current_fingerprint["fingerprint"] != cached_fingerprint:
            return None  # Fingerprint mismatch (source changed)
    
    # Cache valid!
    return meta
```

**Cache Invalidation Reasons**:
1. Cache directory doesn't exist (never cached)
2. Lock file exists (build in progress)
3. `.meta.json` missing or corrupt
4. Artifact spec mismatch (different source/checksum/size)
5. `cached_data/` directory missing
6. Size mismatch (expected vs actual)
7. Source fingerprint mismatch (for fs/backpack, source changed)

#### Concurrent Access Protection

**Lock Mechanism**:
```python
def _acquire_cache_lock(cache_dir, timeout=300):
    """Atomically acquire lock or wait up to timeout seconds."""
    lock_file = cache_dir / ".verify.lock"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    start_time = time.time()
    while True:
        try:
            # Atomic create (fails if exists)
            lock_file.touch(exist_ok=False)
            lock_file.write_text(str(os.getpid()))
            return True
        except FileExistsError:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                return False  # Timeout
            time.sleep(1)  # Wait and retry

def _release_cache_lock(cache_dir):
    """Release lock by removing .verify.lock file."""
    lock_file = cache_dir / ".verify.lock"
    lock_file.unlink(missing_ok=True)
```

**Lock Usage**:
```python
# Try to acquire lock
if not _acquire_cache_lock(cache_dir, timeout=300):
    # Lock timeout, fall back to direct fetch
    return _attempt_fetch_source(item, target_path, ...)

try:
    # Build cache entry (protected by lock)
    success = _build_cache_entry(...)
finally:
    # Always release lock
    _release_cache_lock(cache_dir)
```

**Concurrency Properties**:
- **Prevents duplicate work**: If one process is building cache, others wait
- **Timeout protection**: If lock held too long (300s), fall back to direct fetch
- **Idempotent**: Multiple processes can safely check same cache entry

### Source Fingerprinting

Source fingerprinting enables cache validation for filesystem sources where content may change over time.

#### Motivation

**Problem**: Content-addressable caching assumes sources are immutable. For filesystem sources, this isn't always true:
- Local files may be updated (new experiments, corrected datasets)
- Network filesystems may have clock skew (mtime unreliable)
- Cache may be stale if source changed after caching

**Solution**: Compute and store a "fingerprint" of the source when building cache, then revalidate on cache lookup.

#### Three Fingerprinting Modes

Floability supports three modes with different performance/reliability tradeoffs:

##### Mode 1: "meta" (Metadata-Based)

**Files**:
```python
def fs_fingerprint_file_meta(path):
    stat = path.stat()
    size = stat.st_size
    mtime_ns = stat.st_mtime_ns  # Nanosecond precision
    
    record = f"size:{size}|mtime_ns:{mtime_ns}"
    fingerprint = hashlib.sha256(record.encode("utf-8")).hexdigest()
    
    return {
        "fingerprint": fingerprint,
        "mode": "meta",
        "params": {"size": size, "mtime_ns": mtime_ns}
    }
```

**Directories**:
```python
def fs_fingerprint_dir_meta(root):
    # Collect (relpath, size, mtime_ns) for all files
    h = hashlib.sha256()
    for relpath, size, mtime_ns, _ in collect_files(root):
        record = f"{relpath}|{size}|{mtime_ns}\n"
        h.update(record.encode("utf-8"))
    
    return {"fingerprint": h.hexdigest(), "mode": "meta", ...}
```

**Properties**:
- **Fast**: Only stat() calls, no file reads
- **Low overhead**: Suitable for large directories (thousands of files)
- **Clock-dependent**: Relies on mtime (may be unreliable on NFS)
- **Good for**: Development workflows, frequently-accessed local data

##### Mode 2: "sample" (Content Sampling)

**Files**:
```python
def fs_fingerprint_file_sample(path, sample_bytes=200):
    stat = path.stat()
    size = stat.st_size
    mtime_ns = stat.st_mtime_ns
    
    # Read first N bytes
    h = hashlib.sha256()
    with path.open("rb") as f:
        chunk = f.read(min(sample_bytes, size))
        h.update(chunk)
    sample_hash = h.hexdigest()
    
    record = f"size:{size}|mtime_ns:{mtime_ns}|sample_sha256:{sample_hash}"
    fingerprint = hashlib.sha256(record.encode("utf-8")).hexdigest()
    
    return {
        "fingerprint": fingerprint,
        "mode": "sample",
        "params": {
            "size": size,
            "mtime_ns": mtime_ns,
            "sample_bytes": len(chunk),
            "sample_sha256": sample_hash
        }
    }
```

**Directories**:
```python
def fs_fingerprint_dir_sample(root, sample_bytes=200):
    # Hash (relpath, size, mtime_ns, sha256(first N bytes)) for each file
    h = hashlib.sha256()
    for relpath, size, mtime_ns, content_hash in collect_files(root, sample_bytes):
        record = f"{relpath}|{size}|{mtime_ns}|{content_hash}\n"
        h.update(record.encode("utf-8"))
    
    return {"fingerprint": h.hexdigest(), "mode": "sample", ...}
```

**Properties**:
- **Balanced**: Metadata + partial content
- **Detects corruption**: Catches changes to file headers/structure
- **Moderate overhead**: Reads small amount from each file
- **Good for**: Production workflows with moderate file counts

##### Mode 3: "strict" (Full Content Hash)

**Files**:
```python
def fs_fingerprint_file_strict(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    
    content_hash = h.hexdigest()
    return {
        "fingerprint": content_hash,  # Fingerprint IS content hash
        "mode": "strict",
        "params": {"content_sha256": content_hash}
    }
```

**Directories**:
```python
def fs_fingerprint_dir_strict(root):
    # Hash (relpath, sha256(full content)) for each file
    h = hashlib.sha256()
    for relpath, _, _, content_hash in collect_files(root, full_content=True):
        record = f"{relpath}|{content_hash}\n"
        h.update(record.encode("utf-8"))
    
    return {"fingerprint": h.hexdigest(), "mode": "strict", ...}
```

**Properties**:
- **Cryptographic integrity**: Guaranteed detection of any change
- **High overhead**: Reads all content
- **Slow for large datasets**: Not suitable for TB-scale data
- **Good for**: Critical datasets, small files, verification-heavy workflows

#### Fingerprinting Integration

**CLI Flag**:
```bash
floability data --data-spec data/data.yml \
  --mode fetch \
  --data-cache-mode symlink \
  --fingerprint-mode meta  # or "sample", "strict"
```

**During Cache Build**:
```python
def _build_cache_entry(item, cache_dir, backpack_root, fingerprint_mode, ...):
    # ... download data ...
    
    # Compute source fingerprint (for fs/backpack only)
    source_fingerprint = None
    if item["source_type"] in ("fs", "backpack"):
        from .fingerprint import compute_fingerprint
        source_path = resolve_path(item["source"], backpack_root)
        source_fingerprint = compute_fingerprint(
            str(source_path),
            mode=fingerprint_mode,  # "meta", "sample", or "strict"
            verbose=verbose
        )
    
    # Write to .meta.json
    _write_cache_metadata(
        cache_dir, artifact_spec, content_sha256, actual_size,
        source_fingerprint  # Includes fingerprint, mode, and params
    )
```

**During Cache Lookup**:
```python
def _lookup_cache_entry(cache_dir, artifact_spec, fingerprint_mode, backpack_root, ...):
    # ... validate cache exists ...
    
    # Validate source fingerprint (for fs/backpack)
    if artifact_spec["source_type"] in ("fs", "backpack"):
        cached_fingerprint = meta.get("source_fingerprint")
        if not cached_fingerprint:
            return None  # Old cache format
        
        # Recompute fingerprint from current source
        from .fingerprint import compute_fingerprint
        source_path = resolve_path(artifact_spec["source"], backpack_root)
        current_fingerprint = compute_fingerprint(
            str(source_path),
            mode=fingerprint_mode,  # SAME mode as when cached
            verbose=False
        )
        
        if current_fingerprint["fingerprint"] != cached_fingerprint:
            return None  # Source changed, invalidate cache
```

#### Fingerprinting Performance Comparison

Example: Directory with 1000 files, 10 GB total

| Mode | Time | Overhead | Detects |
|------|------|----------|---------|
| **meta** | ~0.1s | stat() only | Size/mtime changes |
| **sample** (200 bytes) | ~1s | Read 200KB total | Header corruption, size/mtime |
| **strict** | ~30s | Read 10GB | Any byte change |

**Recommendation**:
- **Development**: `meta` (fastest, good enough for local changes)
- **Production**: `sample` (balanced, catches most issues)
- **Critical/Small**: `strict` (full verification)

### Directory vs Single File Handling

Floability handles directories and files differently throughout the stack:

#### Detection and Download

**S3 Sources**:
```python
def _download_to_cache(item, cache_file, backpack_root, ...):
    if stype == "s3":
        # Three-tier detection
        source_obj_type = item.get("source_object_type", "").lower()
        
        is_dir = False
        if source_obj_type == "directory":
            is_dir = True  # Explicit type
        elif source_obj_type == "file":
            is_dir = False
        else:
            # Auto-detect: trailing slash or metadata check
            is_dir = source.endswith('/') or is_s3_directory(source)
        
        if is_dir:
            # Directory: recursive download preserving structure
            s3_directory_download(
                source,
                dest_dir=str(cache_file),  # cache_file is directory
                overwrite=True,
                show_progress=verbose
            )
        else:
            # Single file: download to parent directory
            s3_file_download(
                source,
                dest_dir=str(cache_file.parent),
                filename=cache_file.name,
                overwrite=True
            )
```

**S3 Directory Detection** (`is_s3_directory`):
```python
def is_s3_directory(uri, anonymous=None):
    """Check if S3 URI represents a directory (prefix with multiple objects)."""
    # Parse s3://bucket/prefix/
    bucket, key = parse_s3_uri(uri)
    
    # List objects with prefix
    s3 = boto3.client('s3')
    response = s3.list_objects_v2(Bucket=bucket, Prefix=key, MaxKeys=2)
    
    # If multiple objects with this prefix, it's a directory
    return response.get('KeyCount', 0) > 1
```

**S3 Directory Download** (`s3_directory_download`):
```python
def s3_directory_download(uri, dest_dir, overwrite=False, show_progress=False):
    """Recursively download all objects under S3 prefix."""
    bucket, prefix = parse_s3_uri(uri)
    dest_path = Path(dest_dir)
    dest_path.mkdir(parents=True, exist_ok=True)
    
    # List all objects with prefix
    objects = s3_list_objects(uri, recursive=True)
    
    for obj in objects:
        # Get relative path within prefix
        rel_path = obj['Key'][len(prefix):].lstrip('/')
        target_file = dest_path / rel_path
        
        # Download object
        target_file.parent.mkdir(parents=True, exist_ok=True)
        s3_file_download(
            f"s3://{bucket}/{obj['Key']}",
            dest_dir=str(target_file.parent),
            filename=target_file.name,
            overwrite=overwrite
        )
        
        if show_progress:
            print(f"Downloaded {rel_path} ({obj['Size']} bytes)")
```

**Pelican Sources**: Similar three-tier detection with `is_pelican_directory` and `pelican_directory_download`.

**Filesystem Sources**:
```python
elif stype in ("fs", "backpack"):
    source_path = resolve_path(source, backpack_root)
    
    if source_path.is_file():
        shutil.copy2(source_path, cache_file)
    else:  # Directory
        if cache_file.exists():
            shutil.rmtree(cache_file)  # Remove existing
        shutil.copytree(source_path, cache_file)
```

#### Cache Structure

**Single File**:
```
target_location: "data/model.h5"

Cache structure:
<cache_key>/
  cached_data/
    data/
      model.h5        # Single file
  .meta.json
```

**Directory**:
```
target_location: "data/samples"

Cache structure:
<cache_key>/
  cached_data/
    data/
      samples/        # Directory with full tree
        file1.root
        file2.root
        subdir/
          file3.root
  .meta.json
```

#### Content Hashing

**Single File**: Direct SHA-256 of file content

**Directory**: Merkle-like tree hash:
1. Recursively compute SHA-256 for each file
2. Build sorted list of `(relative_path, file_hash, file_size)`
3. Hash the concatenation: `SHA256(path1:hash1:size1\npath2:hash2:size2\n...)`

**Benefits**:
- Detects structural changes (files added/removed/renamed)
- Detects content changes (any file modified)
- Deterministic (same tree → same hash)
- Efficient (doesn't re-read content during tree hash)

#### Materialization

Both files and directories use the same materialization logic (since cache structure preserves hierarchy):

```python
def _materialize_from_cache(cache_dir, target_path, mode="symlink", ...):
    cached_data_dir = cache_dir / "cached_data"
    
    # Get top-level items from cached_data/
    items = list(cached_data_dir.iterdir())
    
    # Find workflow root by locating first item name in target_path
    first_item_name = items[0].name  # e.g., "data"
    workflow_root = find_parent_of(target_path, first_item_name)
    
    # Materialize each item
    for cached_item in items:
        rel_path = cached_item.relative_to(cached_data_dir)
        target_item = workflow_root / rel_path
        
        if mode == "symlink":
            target_item.symlink_to(cached_item.resolve())
        elif mode == "hardlink":
            if cached_item.is_file():
                os.link(cached_item, target_item)
            else:
                shutil.copytree(cached_item, target_item)  # Fall back to copy
        elif mode == "copy":
            if cached_item.is_file():
                shutil.copy2(cached_item, target_item)
            else:
                shutil.copytree(cached_item, target_item)
```

**Key Insight**: Because cache structure mirrors target structure exactly, materialization doesn't need to distinguish between files and directories. The same top-level symlink works for both.

### Cache Materialization

Cache materialization is the process of making cached data available at target locations in the workflow directory.

#### Three Materialization Modes

##### Mode 1: symlink (Recommended Default)

**Creation**:
```python
target_item.symlink_to(cached_item.resolve())
```

**Properties**:
- **Zero copy**: No data duplication
- **Instant**: O(1) operation regardless of size
- **Read-only convention**: Workflow shouldn't modify data
- **Space efficient**: Multiple instances can share cache

**Use Cases**:
- Read-only workflows (most scientific applications)
- Large datasets (TB-scale)
- Multiple concurrent instances

**Limitations**:
- Requires symlink support (not all filesystems)
- Workflow must respect read-only convention

##### Mode 2: hardlink

**Creation**:
```python
if cached_item.is_file():
    os.link(cached_item, target_item)
else:
    # Hardlinks don't work for directories, fall back to copy
    shutil.copytree(cached_item, target_item)
```

**Properties**:
- **Shared inode**: File appears in both locations
- **Space efficient**: No data duplication (for files)
- **Independent**: Can be deleted independently
- **Modification affects both**: Changes visible through both links

**Use Cases**:
- Workflows that need writable paths (in-place updates)
- When symlink support unavailable
- Filesystem-aware applications (detect hardlinks)

**Limitations**:
- Only works for files on same filesystem
- Directories must be copied (no directory hardlinks)
- Modification affects cache (potentially dangerous)

##### Mode 3: copy

**Creation**:
```python
if cached_item.is_file():
    shutil.copy2(cached_item, target_item)  # Preserves metadata
else:
    shutil.copytree(cached_item, target_item)
```

**Properties**:
- **Full independence**: Target is separate copy
- **Writable**: Workflow can modify freely
- **Space overhead**: Doubles storage requirement
- **Slow**: O(size) operation

**Use Cases**:
- Workflows that modify data in-place
- Testing (don't want to affect cache)
- When symlink/hardlink not supported

**Limitations**:
- Doubles storage requirement
- Slow for large datasets (minutes to hours)
- No longer benefits from shared cache

#### Materialization Algorithm (Feb 2026)

The simplified materialization algorithm:

```python
def _materialize_from_cache(cache_dir, target_path, mode, verbose):
    cached_data_dir = cache_dir / "cached_data"
    
    # 1. Get all top-level items from cached_data/
    items = list(cached_data_dir.iterdir())
    # Example: ["data"] for cached_data/data/samples/file.root
    
    # 2. Find workflow root by locating first item name in target_path
    first_item_name = items[0].name  # "data"
    workflow_root = target_path
    
    # Walk up until we find where "data" should be
    while workflow_root.name != first_item_name and workflow_root.parent != workflow_root:
        workflow_root = workflow_root.parent
    
    # If we found "data", go up one more to get the root
    if workflow_root.name == first_item_name:
        workflow_root = workflow_root.parent
    
    # 3. Materialize each top-level item
    for cached_item in items:
        rel_path = cached_item.relative_to(cached_data_dir)
        target_item = workflow_root / rel_path
        
        # Ensure parent exists
        target_item.parent.mkdir(parents=True, exist_ok=True)
        
        # Remove existing (stale symlinks, old data)
        if target_item.exists() or target_item.is_symlink():
            if target_item.is_dir() and not target_item.is_symlink():
                shutil.rmtree(target_item)
            else:
                target_item.unlink()
        
        # Create link/copy based on mode
        if mode == "symlink":
            target_item.symlink_to(cached_item.resolve())
        elif mode == "hardlink":
            # ... (see above)
        elif mode == "copy":
            # ... (see above)
    
    return True
```

**Example**:
```
Cache:
  cached_data/data/samples/test/file.root

Target path: /instance/workflow/data/samples/test

Step 1: Items = ["data"]
Step 2: First item = "data", walk up from target_path:
  - /instance/workflow/data/samples/test
  - /instance/workflow/data/samples
  - /instance/workflow/data  ← name matches "data"
  - /instance/workflow  ← go up one more, this is workflow_root
Step 3: Materialize:
  - Symlink /instance/workflow/data → cached_data/data
Result: /instance/workflow/data/samples/test/file.root accessible via symlink
```

**Key Properties**:
- **Single top-level symlink**: Not per-file, but per-data item's top directory
- **Structure preserved**: Full nested hierarchy works automatically
- **Predictable**: Always creates symlink at the level where item name appears in target path
- **Handles multiple items**: If cache has multiple top-level items, each gets its own symlink

#### Cache Cleanup

**Manual Cleanup**:
```bash
# Remove all cache entries
rm -rf ~/floability-data-cache

# Remove specific cache entry
rm -rf ~/floability-data-cache/<cache_key>

# Remove only data, keep metadata
rm -rf ~/floability-data-cache/<cache_key>/cached_data
```

**Automated Cleanup** (Future):
- LRU eviction when cache size exceeds threshold
- Age-based pruning (remove entries older than N days)
- Reference counting (remove if no instances using)

**Cache Size Estimation**:
```bash
# Total cache size
du -sh ~/floability-data-cache

# Per-entry size
du -sh ~/floability-data-cache/*

# Find largest cache entries
du -sh ~/floability-data-cache/* | sort -h | tail -10
```

---

## Implementation Summary

### Key Design Decisions

1. **Declarative Specification**: Data requirements separate from notebook code
2. **Content-Addressable Caching**: Same source → same cache entry
3. **Profile-Based Configuration**: Environment-specific sources without code changes
4. **Multi-Source Fallback**: Resilient access across network topologies
5. **Three Operation Modes**: Check (metadata), Fetch (download), Verify (integrity)
6. **Fingerprinting**: Validate filesystem sources haven't changed
7. **Flexible Materialization**: Symlink (fast), hardlink (independent), copy (isolated)
8. **Directory Support**: First-class support for directory trees (S3, Pelican, fs)

### Portability Mechanisms

| Challenge | Solution | Benefit |
|-----------|----------|---------|
| Heterogeneous storage | Source type abstraction | Unified access to HTTP/S3/Pelican/fs |
| Site-specific paths | Profile-based configuration | Same backpack, different sources |
| Network topology | Multi-source fallback | Automatic adaptation |
| Data duplication | Content-addressable cache | Shared cache across instances |
| Large datasets | Symlink materialization | Zero-copy instantiation |
| Source changes | Fingerprinting | Detect stale cache |
| Integrity | Checksums + verification | Reproducibility guarantees |

### Performance Characteristics

| Operation | Time Complexity | I/O | Network |
|-----------|----------------|-----|---------|
| **Check** | O(items) | Metadata only | HEAD requests |
| **Fetch (cache hit)** | O(items) | Symlink creation | None |
| **Fetch (cache miss)** | O(total_size) | Full download | Full download |
| **Verify** | O(total_size) | Full read | None (if cached) |
| **Fingerprint (meta)** | O(files) | stat() only | None |
| **Fingerprint (sample)** | O(files × sample_bytes) | Partial read | None |
| **Fingerprint (strict)** | O(total_size) | Full read | None |

### Implementation Files

- **`floability/data/data_handler.py`**: Core orchestration (check/fetch/verify)
- **`floability/data/http_file_utils.py`**: HTTP download utilities
- **`floability/data/s3_file_utils.py`**: S3 file/directory operations
- **`floability/data/pelican_file_utils.py`**: Pelican/OSDF file/directory operations
- **`floability/data/fs_file_utils.py`**: Filesystem utilities
- **`floability/data/fingerprint.py`**: Source fingerprinting (meta/sample/strict)
- **`floability/ops/data.py`**: CLI operation handlers

---

## For Paper Writing

### Suggested Structure for Section 3 (Declarative Data Spec)

1. **Introduction**: Motivation for declarative specs (portability, separation of concerns)
2. **YAML Structure**: Brief overview with example
3. **Portability Features**:
   - Profile-based configuration (figure: same backpack, 3 different profiles)
   - Source type abstraction (table of supported types)
   - Multi-source fallback (example with 4 fallback sources)
   - Target location consistency (code snippet showing notebook independence)
4. **Real-World Example**: One of your applications with 2-3 profiles

### Suggested Structure for Section 4 (Implementation)

1. **Three Operations**:
   - Check: Metadata-only pre-flight
   - Fetch: Download with caching
   - Verify: Integrity validation
   - Table comparing when to use each
2. **Local Data Cache** (Big subsection):
   - Architecture: Content-addressable, lock-based concurrency
   - Cache key computation: Artifact spec, deterministic hashing
   - Cache structure: Diagram showing cache_key/cached_data/.meta.json
   - Building vs. lookup: Flow diagram
3. **Source Fingerprinting**:
   - Problem: Filesystem sources can change
   - Solution: Three modes (table comparing meta/sample/strict)
   - Integration: When computed, when validated
4. **Directory Handling**:
   - Detection: Three-tier priority
   - Download: Recursive with structure preservation
   - Hashing: Merkle-like tree hash
   - Materialization: Single top-level symlink
5. **Performance**: Table showing I/O characteristics

### Figures/Tables to Include

1. **Figure: Profile-based portability** - Same backpack with local/S3/Pelican profiles
2. **Table: Source types** - Type, protocol, use case, example
3. **Figure: Cache architecture** - Directory structure with annotations
4. **Table: Fingerprinting modes** - Mode, time, overhead, detects
5. **Figure: Materialization flow** - Cache → workflow symlink diagram
6. **Table: Operation comparison** - Check/fetch/verify characteristics

### Metrics to Highlight

- **Cache hit rate**: X% in your experiments across 3 sites
- **Materialization time**: <1s vs. Xmin for copy (for Y GB dataset)
- **Storage savings**: N instances sharing 1 cache vs. N copies
- **Network efficiency**: Multi-source fallback used Z% of time at Site B

---

*Document generated: February 8, 2026*  
*For internal use in paper writing - not for direct inclusion*
