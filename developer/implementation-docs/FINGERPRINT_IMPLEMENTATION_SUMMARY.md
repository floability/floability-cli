# Filesystem Fingerprinting Implementation - Summary

## Completed Implementation

### Core Fingerprinting Module
✅ **File**: `src/floability/data/fingerprint.py`
- Implements three fingerprint modes for filesystem sources:
  - `meta`: Fast, uses file size + mtime (metadata only)
  - `sample`: Medium speed, uses size + mtime + SHA256 of first 200 bytes
  - `strict`: Slow but thorough, full content SHA256 hash
- Supports both files and directories
- Directory fingerprinting: recursive walk with sorted paths for determinism
- Handles symlinks (skips them to avoid issues)
- Future extension hooks for HTTP, S3, Pelican sources

### Cache Integration
✅ **File**: `src/floability/data/data_handler.py`
- Extended `.meta.json` schema with:
  - `source_fingerprint`: Hex digest of source fingerprint
  - `fingerprint_mode`: Mode used (meta/sample/strict)
  - `fingerprint_params`: Parameters (size, mtime, sample_bytes, etc.)
- Updated `_write_cache_metadata()`: Stores fingerprint data
- Updated `_lookup_cache_entry()`: Validates fingerprints on cache reuse
- Updated `_build_cache_entry()`: Computes fingerprints during cache creation
- Updated `_fetch_single_item()`: Passes fingerprint_mode through call chain

### CLI Integration
✅ **Files**: `src/floability/cli.py`, `src/floability/ops/data.py`, `src/floability/ops/run.py`, `src/floability/ops/instance.py`

Added `--fingerprint-mode` flag to:
- ✅ `floability data` command (check, fetch, verify modes)
- ✅ `floability run` command
- ✅ `floability execute` command  
- ✅ `floability instance create` command

All commands support:
- `--fingerprint-mode meta` (default - fast, metadata only)
- `--fingerprint-mode sample` (first N bytes + metadata)
- `--fingerprint-mode strict` (full content hash)
- Works alongside `--data-cache-mode` (off/symlink/hardlink/copy)

### Key Features

#### 1. Cache Key Unchanged
- Existing cache-key generation untouched (based on artifact spec hash)
- Fingerprint is for validation only, not cache key computation
- Multiple runs with same spec use same cache directory

#### 2. Automatic Invalidation
- **Meta mode**: Invalidates on mtime or size change
- **Sample mode**: Invalidates on header changes or metadata changes
- **Strict mode**: Invalidates on any content change
- Directory changes: Detects file add/remove/rename/modify

#### 3. Intelligent Warnings
- Large directories with strict mode: warns about performance
- Many files with sample mode: warns about processing time
- Missing source fingerprint: indicates legacy cache format

#### 4. Backward Compatibility
- Old cache entries without fingerprints gracefully invalidated
- Logs show "no source fingerprint (old cache format)"
- Cache rebuilt with new fingerprint metadata

#### 5. Filesystem-Only Implementation
- Currently implements `fs` and `backpack` source types
- HTTP, Pelican, S3 sources have TODO stub functions
- Easy to extend for additional source types

### Usage Examples

#### Data Command
```bash
# Fetch with meta mode (default)
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose

# Verify with sample mode
floability data --mode verify --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode sample --verbose

# Strict mode for critical data
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode copy --fingerprint-mode strict --verbose
```

#### Run Command
```bash
# Run backpack with caching and fingerprinting
floability run --backpack example/matrix-multiplication \
  --data-cache-mode symlink --fingerprint-mode meta --verbose

# Disable caching entirely
floability run --backpack example/matrix-multiplication \
  --data-cache-mode off
```

#### Instance Create
```bash
# Create instance with sample mode
floability instance create --backpack example/matrix-multiplication \
  --name my-instance --data-cache-mode symlink \
  --fingerprint-mode sample --verbose
```

### Testing Strategy

✅ **File**: `TEST_FINGERPRINTING.md`
- 14 comprehensive test scenarios
- Covers all fingerprint modes
- Tests cache reuse and invalidation
- Directory operations (add/remove/rename)
- Integration with run/execute/instance commands
- Performance comparisons
- Legacy cache migration
- Debugging tips and validation checklist

### Performance Characteristics

**Meta Mode** (Default)
- Speed: Fastest (milliseconds)
- Use case: Development, frequent iteration
- Detects: File modifications (mtime/size changes)
- Overhead: Minimal (stat calls only)

**Sample Mode**
- Speed: Medium (seconds for many files)
- Use case: Balance between speed and safety
- Detects: Header changes, metadata changes
- Overhead: Reads first 200 bytes per file

**Strict Mode**
- Speed: Slowest (minutes for large directories)
- Use case: Production, critical data validation
- Detects: Any content changes anywhere in files
- Overhead: Full file reads, complete hash computation

### What's NOT Included (Future Work)

❌ HTTP source fingerprinting (ETag, Last-Modified headers)
❌ S3 source fingerprinting (ETag, metadata)
❌ Pelican source fingerprinting
❌ Post-processing support (unzip, untar)
❌ Configurable sample size per data item
❌ Parallel fingerprinting for large directories

### Files Modified

1. **New**: `src/floability/data/fingerprint.py` (555 lines)
2. **Modified**: `src/floability/data/data_handler.py` (+150 lines)
3. **Modified**: `src/floability/cli.py` (+15 lines)
4. **Modified**: `src/floability/ops/data.py` (+3 lines)
5. **Modified**: `src/floability/ops/run.py` (+1 line)
6. **Modified**: `src/floability/ops/instance.py` (+1 line)
7. **New**: `TEST_FINGERPRINTING.md` (test strategy)
8. **Existing**: `FLOABILITY_DATA_OPERATIONS_SUMMARY.md` (documentation)

### Design Principles Followed

✅ No changes to existing cache-key generation
✅ Source-type specific implementation (fs/backpack only)
✅ Reusable and extensible design
✅ Clear separation: cache key vs validation
✅ Graceful degradation (old caches work)
✅ Comprehensive logging
✅ User-configurable modes
✅ Backward compatible

### Next Steps (Future PRs)

1. **HTTP Fingerprinting**
   - Use ETag header for validation
   - HEAD request for metadata
   - Partial GET for sample mode

2. **Pelican Fingerprinting**
   - Pelican-specific APIs
   - Fall back to HTTP methods

3. **S3 Fingerprinting**
   - Use S3 ETag and metadata
   - head_object for meta mode
   - get_object with Range for sample

4. **Performance Optimizations**
   - Parallel fingerprinting
   - Incremental directory hashing
   - Fingerprint caching

5. **Configuration**
   - Per-item fingerprint mode in data.yml
   - Configurable sample size
   - Fingerprint cache TTL

---

## Testing Instructions

See `TEST_FINGERPRINTING.md` for complete testing strategy.

Quick smoke test:
```bash
# Setup test backpack
mkdir -p test-backpack/data
echo "test content" > test-backpack/data/file.txt

# Create data spec
cat > test-backpack/data/data.yml << 'EOF'
schema_version: 1.0
default_profile: test
data_profiles:
  test:
    data:
      - name: test_file
        source_type: backpack
        source: data/file.txt
        target_location: data/file.txt
EOF

# Test with fingerprinting
floability data --mode fetch --data-spec test-backpack/data/data.yml \
  --backpack test-backpack --data-cache-mode symlink \
  --fingerprint-mode meta --verbose

# Check cache metadata
find flo_data_cache -name ".meta.json" -exec cat {} \; | jq .

# Cleanup
rm -rf test-backpack flo_data_cache
```

---

**Status**: ✅ Complete and ready for testing
**Branch**: dev/data-handling
**Target**: Filesystem sources only (HTTP/S3/Pelican in future PRs)
