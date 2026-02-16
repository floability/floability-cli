# Quick Start: Filesystem Fingerprinting in Floability

## What is it?

Filesystem fingerprinting validates cached data by checking if source files have changed. This ensures your cached data stays fresh while avoiding unnecessary re-downloads when sources haven't changed.

## Three Modes

| Mode | Speed | Detects | Best For |
|------|-------|---------|----------|
| `meta` | ⚡ Fastest | File size/time changes | Development, frequent iterations |
| `sample` | ⚡⚡ Medium | Header + metadata changes | Balanced workflows |
| `strict` | 🐢 Slowest | Any content changes | Production, critical data |

## Quick Examples

### 1. Enable Caching with Fingerprinting (Recommended)

```bash
# Fetch data with caching enabled (default: meta mode)
floability data --mode fetch \
  --data-spec example/rag-lite-bm25/data/data.yml \
  --backpack example/rag-lite-bm25 \
  --data-cache-mode symlink \
  --verbose
```

### 2. Run a Backpack with Caching

```bash
# Run with default caching and fingerprinting
floability run \
  --backpack example/matrix-multiplication \
  --data-cache-mode symlink \
  --fingerprint-mode meta \
  --verbose
```

### 3. Strict Mode for Production

```bash
# Use strict validation for critical data
floability data --mode verify \
  --data-spec data/data.yml \
  --backpack . \
  --data-cache-mode copy \
  --fingerprint-mode strict \
  --verbose
```

### 4. Disable Caching (Legacy Behavior)

```bash
# Turn off caching entirely
floability run \
  --backpack example/matrix-multiplication \
  --data-cache-mode off
```

## Command Options

All commands (`data`, `run`, `execute`, `instance create`) support:

```bash
--data-cache-mode [off|symlink|hardlink|copy]
  off: No caching (direct download each time)
  symlink: Cache and link (default, read-only)
  hardlink: Cache and hard-link (same filesystem)
  copy: Cache and copy (isolated, modifiable)

--fingerprint-mode [meta|sample|strict]
  meta: Fast, metadata only (default)
  sample: First 200 bytes + metadata
  strict: Full content hash

--force-data-cache
  Rebuild cache even if valid

--verbose
  Show detailed fingerprinting logs
```

## How It Works

1. **First Run**: Downloads data → Computes fingerprint → Stores in cache
2. **Second Run**: Checks cache → Recomputes fingerprint → Compares
   - If fingerprints match: Reuse cache ✅
   - If fingerprints differ: Invalidate & rebuild ♻️

## What Gets Fingerprinted?

- ✅ Filesystem files (`source_type: fs` or `backpack`)
- ❌ HTTP downloads (not yet implemented)
- ❌ Pelican sources (not yet implemented)
- ❌ S3 sources (not yet implemented)

## Cache Location

```
<base-dir>/flo_data_cache/
  <cache-key>/
    data/                # Cached content
      your-file.csv
    .meta.json          # Metadata + fingerprint
```

## Inspecting Cache

```bash
# View cache metadata
find flo_data_cache -name ".meta.json" -exec cat {} \; | jq .

# Check specific fingerprint
cat flo_data_cache/<cache-key>/.meta.json | jq '{
  fingerprint: .source_fingerprint,
  mode: .fingerprint_mode,
  params: .fingerprint_params
}'
```

## Common Scenarios

### Development: Fast Iteration
```bash
floability run --backpack . \
  --data-cache-mode symlink \
  --fingerprint-mode meta
```
- Fastest mode
- Detects file modifications via mtime
- Good for development cycles

### Testing: Balance Speed and Safety
```bash
floability run --backpack . \
  --data-cache-mode symlink \
  --fingerprint-mode sample
```
- Medium speed
- Detects header changes
- Good for testing phase

### Production: Maximum Validation
```bash
floability run --backpack . \
  --data-cache-mode copy \
  --fingerprint-mode strict
```
- Full content validation
- Isolated data (copy mode)
- Good for production runs

### Debugging: See What's Happening
```bash
floability data --mode fetch \
  --data-spec data/data.yml \
  --backpack . \
  --data-cache-mode symlink \
  --fingerprint-mode meta \
  --verbose \
  --force-data-cache
```
- Shows fingerprint computation
- Shows cache operations
- Rebuilds cache for inspection

## Troubleshooting

### Cache Not Reusing?
- Check fingerprint_mode matches previous run
- Verify source files haven't changed
- Use `--verbose` to see why cache invalidated

### Slow Performance?
- Switch from `strict` to `sample` or `meta`
- Use `meta` mode for large directories
- Consider `--data-cache-mode off` if caching overhead too high

### Old Cache Format?
- Old caches without fingerprints automatically invalidated
- Will see: "Cache invalid: no source fingerprint (old cache format)"
- Cache will rebuild with new fingerprint metadata

### Source Changed But Cache Not Invalidating?
- Meta mode only checks mtime/size (use sample or strict)
- Sample mode only checks first 200 bytes (use strict)
- Strict mode checks full content (slowest but catches everything)

## Performance Tips

1. **Use meta mode by default** - Fast enough for most cases
2. **Use sample for critical headers** - CSV files, JSON with version info
3. **Reserve strict for small, critical data** - Checksums, signatures, configs
4. **Consider cache mode**:
   - `symlink`: Fastest, read-only
   - `hardlink`: Fast, same filesystem only
   - `copy`: Slower, but isolated

## Verification

Run the verification script:
```bash
python3 verify_fingerprinting.py
```

This checks:
- Module imports work
- Function signatures correct
- Fingerprinting computes correctly
- All three modes functional

## Learn More

- **Complete Testing Strategy**: `TEST_FINGERPRINTING.md`
- **Implementation Details**: `FINGERPRINT_IMPLEMENTATION_SUMMARY.md`
- **Data Operations Overview**: `FLOABILITY_DATA_OPERATIONS_SUMMARY.md`

## Questions?

- Does caching work without fingerprinting? **No** - fingerprinting is required for validation
- Can I disable fingerprinting? **Yes** - use `--data-cache-mode off`
- Does it work for HTTP sources? **Not yet** - filesystem only for now
- Will old caches work? **Yes** - they'll be invalidated and rebuilt with fingerprints
- Is it backward compatible? **Yes** - no breaking changes to existing workflows

---

**Ready to test?** Start with `TEST_FINGERPRINTING.md` Scenario 1!
