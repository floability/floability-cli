# Testing Strategy for Filesystem Fingerprinting

## Overview
This document outlines the testing strategy for the new filesystem fingerprinting feature in Floability's data caching system.

## Test Environment Setup

### 1. Create Test Backpack Structure
```bash
cd /users/mislam5/floability-project/floability-cli
mkdir -p test-fingerprint-backpack/{data,workflow,software,compute}
cd test-fingerprint-backpack
```

### 2. Create Test Data Files
```bash
# Create a simple text file
echo "Hello, World!" > data/test-file.txt

# Create a directory with multiple files
mkdir -p data/test-dir
echo "File 1 content" > data/test-dir/file1.txt
echo "File 2 content" > data/test-dir/file2.txt
echo "File 3 content" > data/test-dir/file3.txt

# Create a larger file for sample testing
dd if=/dev/urandom of=data/large-file.dat bs=1M count=5

# Create a nested directory structure
mkdir -p data/nested/subdir1/subdir2
echo "Deep file" > data/nested/subdir1/subdir2/deep.txt
echo "Shallow file" > data/nested/file.txt
```

### 3. Create Data Specification (data/data.yml)
```bash
cat > data/data.yml << 'EOF'
schema_version: 1.0
default_profile: local_files

data_profiles:
  local_files:
    policy:
      retry_attempts: 0
      timeout: 30
      size_tolerance_bytes: 10
      run_operation: fetch
      verification_type: size_only

    data:
      - name: simple_file
        source_type: backpack
        source: data/test-file.txt
        target_location: data/test-file.txt
        expected_size: 14

      - name: test_directory
        source_type: backpack
        source: data/test-dir
        target_location: data/test-dir
        expected_size: 1000

      - name: large_file
        source_type: backpack
        source: data/large-file.dat
        target_location: data/large-file.dat
        expected_size: 5242880

      - name: nested_directory
        source_type: backpack
        source: data/nested
        target_location: data/nested
EOF
```

---

## Test Scenarios

### Scenario 1: Initial Cache Build with Fingerprinting

**Objective**: Verify that cache entries are created with source fingerprints

**Test Steps**:
```bash
# Clean any existing cache
rm -rf flo_data_cache/

# Fetch data with meta mode (default)
floability data \
  --mode fetch \
  --data-spec data/data.yml \
  --backpack . \
  --data-cache-mode symlink \
  --fingerprint-mode meta \
  --verbose

# Verify cache was created with fingerprints
ls -la flo_data_cache/
cat flo_data_cache/*/.[m]eta.json | grep -i fingerprint
```

**Expected Results**:
- Cache directories created under `flo_data_cache/`
- Each `.meta.json` contains `source_fingerprint`, `fingerprint_mode`, and `fingerprint_params` fields
- Log shows fingerprint computation messages
- Files materialized in `workflow/data/`

---

### Scenario 2: Cache Reuse with Unchanged Sources

**Objective**: Verify that cache is reused when source fingerprints match

**Test Steps**:
```bash
# First fetch (builds cache)
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose

# Second fetch (should reuse cache)
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose \
  --force-fetch
```

**Expected Results**:
- First run: "Building cache entry" messages
- Second run: "Cache hit" and "Source fingerprint valid" messages
- Second run: No download/copy operations, only materialization from cache
- Faster execution on second run

---

### Scenario 3: Cache Invalidation on Content Change (Meta Mode)

**Objective**: Verify meta mode detects mtime changes

**Test Steps**:
```bash
# Initial fetch
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose

# Touch file (change mtime but not content)
sleep 2
touch data/test-file.txt

# Fetch again
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose \
  --force-fetch
```

**Expected Results**:
- Log shows "Cache invalid: source fingerprint mismatch"
- Cache rebuilt with new fingerprint
- New mtime_ns in fingerprint_params

---

### Scenario 4: Cache Invalidation on Content Change (Sample Mode)

**Objective**: Verify sample mode detects header changes

**Test Steps**:
```bash
# Initial fetch with sample mode
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode sample --verbose

# Modify beginning of file (affects sample)
echo "Modified content" > data/test-file.txt

# Fetch again
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode sample --verbose \
  --force-fetch
```

**Expected Results**:
- Cache invalidated due to sample hash change
- Log shows different sample_sha256 values
- Cache rebuilt

---

### Scenario 5: Cache Invalidation on Content Change (Strict Mode)

**Objective**: Verify strict mode detects any content changes

**Test Steps**:
```bash
# Initial fetch with strict mode
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode strict --verbose

# Modify end of file (sample mode wouldn't catch this)
echo "Appended content" >> data/large-file.dat

# Fetch again
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode strict --verbose \
  --force-fetch
```

**Expected Results**:
- Cache invalidated due to full content hash change
- Warning about large file size with strict mode
- Cache rebuilt with new content hash

---

### Scenario 6: Directory Structure Changes (Meta Mode)

**Objective**: Verify directory fingerprinting detects file additions/deletions

**Test Steps**:
```bash
# Initial fetch
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose

# Add a new file to directory
echo "New file" > data/test-dir/file4.txt

# Fetch again
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose \
  --force-fetch

# Remove a file
rm data/test-dir/file4.txt

# Fetch again
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose \
  --force-fetch
```

**Expected Results**:
- Cache invalidated when file added (file_count changes)
- Cache invalidated when file removed (file_count changes)
- Logs show fingerprint mismatches

---

### Scenario 7: Directory File Rename Detection

**Objective**: Verify fingerprinting detects file renames within directories

**Test Steps**:
```bash
# Initial fetch
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose

# Rename a file
mv data/test-dir/file1.txt data/test-dir/renamed.txt

# Fetch again
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose \
  --force-fetch
```

**Expected Results**:
- Cache invalidated (relative path changed in fingerprint)
- Log shows source fingerprint mismatch
- Cache rebuilt

---

### Scenario 8: Force Cache Rebuild

**Objective**: Verify --force-data-cache flag bypasses fingerprint validation

**Test Steps**:
```bash
# Initial fetch
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose

# Force rebuild without changing source
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose \
  --force-fetch --force-data-cache
```

**Expected Results**:
- Cache rebuilt even though source unchanged
- Log shows "Building cache entry" instead of cache lookup

---

### Scenario 9: Different Fingerprint Modes on Same Data

**Objective**: Verify that different fingerprint modes create separate validations

**Test Steps**:
```bash
# Fetch with meta mode
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose

# Examine cache metadata
cat flo_data_cache/*/.[m]eta.json | jq '.fingerprint_mode'

# Fetch with sample mode (same cache key, different validation)
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode sample --verbose \
  --force-fetch

# Fetch with strict mode
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode strict --verbose \
  --force-fetch
```

**Expected Results**:
- Cache entry reused (same cache key from spec hash)
- Fingerprint recomputed with new mode
- If source unchanged, cache still valid
- Cache metadata shows last used fingerprint mode

---

### Scenario 10: Verify Command with Fingerprinting

**Objective**: Test fingerprinting with verify operation

**Test Steps**:
```bash
# Verify with meta mode
floability data --mode verify --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose

# Modify source
echo "Modified" > data/test-file.txt

# Verify again (should invalidate and refetch)
floability data --mode verify --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose
```

**Expected Results**:
- First verify: Cache valid, verification passes
- After modification: Cache invalidated, data refetched, verification passes
- Integrity checks (size, checksum) still work correctly

---

### Scenario 11: Legacy Cache Migration

**Objective**: Verify handling of old cache entries without fingerprints

**Test Steps**:
```bash
# Create a mock old cache entry (without fingerprints)
mkdir -p flo_data_cache/test_cache/data
echo "Test" > flo_data_cache/test_cache/data/test.txt
cat > flo_data_cache/test_cache/.meta.json << 'EOF'
{
  "artifact_spec": {"source": "data/test-file.txt", "source_type": "backpack"},
  "content_sha256": "abc123",
  "actual_size": 5,
  "created_at_iso": "2025-01-01T00:00:00Z"
}
EOF

# Try to use cache with fingerprinting enabled
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose
```

**Expected Results**:
- Log shows "Cache invalid: no source fingerprint (old cache format)"
- Cache entry rebuilt with new fingerprint metadata
- Old cache entries gracefully invalidated

---

### Scenario 12: Performance Comparison

**Objective**: Compare performance across fingerprint modes

**Test Steps**:
```bash
# Create larger test data
mkdir -p data/perf-test
for i in {1..100}; do
  echo "File $i content" > data/perf-test/file$i.txt
done

# Test meta mode
time floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --force-data-cache

# Test sample mode
time floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode sample --force-data-cache

# Test strict mode
time floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode strict --force-data-cache
```

**Expected Results**:
- Meta mode: Fastest (metadata only)
- Sample mode: Medium (reads first N bytes)
- Strict mode: Slowest (reads all content)
- Warning messages for strict mode with many/large files

---

## Integration with Run/Execute Commands

### Scenario 13: Run Backpack with Fingerprinting

**Objective**: Verify fingerprinting works when running a backpack with data

**Test Steps**:
```bash
# Run with default meta mode
floability run \
  --backpack test-fingerprint-backpack \
  --data-cache-mode symlink \
  --fingerprint-mode meta \
  --verbose

# Run with sample mode
floability run \
  --backpack test-fingerprint-backpack \
  --data-cache-mode symlink \
  --fingerprint-mode sample \
  --verbose

# Run with strict mode
floability run \
  --backpack test-fingerprint-backpack \
  --data-cache-mode symlink \
  --fingerprint-mode strict \
  --verbose

# Run with cache disabled
floability run \
  --backpack test-fingerprint-backpack \
  --data-cache-mode off \
  --verbose
```

**Expected Results**:
- Data fetched during run with appropriate fingerprinting
- Cache reused correctly across runs
- Logs show fingerprint computation during data phase
- Workflow executes successfully with cached data

---

### Scenario 14: Instance Create with Fingerprinting

**Objective**: Verify fingerprinting works when creating instances

**Test Steps**:
```bash
# Create instance with meta mode
floability instance create \
  --backpack test-fingerprint-backpack \
  --name test-instance-meta \
  --data-cache-mode symlink \
  --fingerprint-mode meta \
  --verbose

# Create instance with sample mode
floability instance create \
  --backpack test-fingerprint-backpack \
  --name test-instance-sample \
  --data-cache-mode symlink \
  --fingerprint-mode sample \
  --verbose

# Create instance with cache disabled
floability instance create \
  --backpack test-fingerprint-backpack \
  --name test-instance-nocache \
  --data-cache-mode off \
  --verbose
```

**Expected Results**:
- Instance created with data materialized using fingerprinting
- Cache shared across different instances
- Each instance has properly materialized data
- Fingerprint validation ensures data integrity

---

## Validation Checklist

After running test scenarios, verify:

- [ ] Cache entries contain fingerprint metadata
- [ ] Fingerprints are deterministic (same source = same fingerprint)
- [ ] Cache invalidates on real changes
- [ ] Cache reuses when source unchanged
- [ ] All three modes (meta, sample, strict) work correctly
- [ ] Directory fingerprinting works for files and directories
- [ ] Warnings shown for large directories with strict mode
- [ ] Legacy cache entries are handled gracefully
- [ ] CLI flag `--fingerprint-mode` works correctly
- [ ] Verbose logging provides useful information
- [ ] No errors or crashes during normal operations

---

## Debugging Tips

### Inspect Cache Metadata
```bash
# View all cache entries
find flo_data_cache -name ".meta.json" -exec cat {} \; | jq .

# Check fingerprint for specific cache entry
cat flo_data_cache/<cache_key>/.meta.json | jq '{
  fingerprint: .source_fingerprint,
  mode: .fingerprint_mode,
  params: .fingerprint_params
}'
```

### Monitor Cache Operations
```bash
# Watch cache directory during operations
watch -n 1 'ls -lR flo_data_cache/'

# Monitor logs
floability data --mode fetch --data-spec data/data.yml --backpack . \
  --data-cache-mode symlink --fingerprint-mode meta --verbose 2>&1 | tee fetch.log
```

### Test Fingerprint Module Directly
```bash
# Test Python module directly
python3 -c "
from floability.data.fingerprint import compute_fingerprint
import json

result = compute_fingerprint('data/test-file.txt', 'meta', verbose=True)
print(json.dumps(result, indent=2))
"
```

---

## Expected Warnings

During testing, you may see expected warnings:

- `"[fingerprint:strict] Warning: Directory is X MB, strict mode will read all content"` - Normal for large directories with strict mode
- `"[fingerprint:sample] Warning: Directory has X files, sampling may take time"` - Normal for directories with many files
- `"[cache] Cache invalid: no source fingerprint (old cache format)"` - Expected when using old cache entries
- `"[cache] Warning: Failed to validate source fingerprint"` - May occur if source was deleted

---

## Cleanup

After testing:
```bash
# Remove test backpack
cd /users/mislam5/floability-project/floability-cli
rm -rf test-fingerprint-backpack/

# Clean cache
rm -rf flo_data_cache/
```

---

## Success Criteria

The implementation is successful if:

1. ✅ All test scenarios pass without errors
2. ✅ Cache invalidates on real source changes
3. ✅ Cache reuses correctly when sources unchanged
4. ✅ All three fingerprint modes work as expected
5. ✅ Directory fingerprinting handles files and directories
6. ✅ Performance is acceptable (meta < sample < strict)
7. ✅ Logging is clear and helpful
8. ✅ No breaking changes to existing cache functionality
9. ✅ Legacy cache entries handled gracefully
10. ✅ CLI integration works smoothly
