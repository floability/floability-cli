# Data caching

Floability can cache data artifacts to avoid repeated downloads or copies across runs. The cache is stored under a shared directory, and items are materialized into each instance using your preferred mode: symlink, hardlink, or copy.

## Where the cache lives

- Base directory: controlled by the `--base-dir` CLI option. Defaults to `.` (current directory) when not specified.
- Cache root: `<base-dir>/flo_data_cache/`
- Per-artifact directory: `<base-dir>/flo_data_cache/<cache_key>/`

Each artifact directory contains:

- `data/` — the cached bytes (file or directory tree)
- `.meta.json` — metadata: artifact spec (normalized), content SHA-256, size, created timestamps
- `.verify.lock` — a short-lived lock while building/verifying the cache entry (prevents duplicate work in concurrent runs)

Example:

```
<base-dir>/
  flo_data_cache/
    7a8c...e1b0/
      data/
        sample.csv
      .meta.json
      .verify.lock  # only during build/verify
```

## How cache keys are computed

A deterministic cache key is derived from a normalized "artifact spec" that only includes fields affecting the bytes:

- Source(s) and source types (with local sources resolved to absolute paths)
- Expected size (if specified)
- Checksum (if specified)
- Content type (optional)
- Post-process settings (if supported)

For multi-source items (`sources:`), all sources are included in order.

## Materialization modes

When fetching or verifying, cached content is materialized to the instance target path using the selected mode:

- `symlink` (default): create a symlink from the cache to the target — fast and space-efficient; best for read-only workloads.
- `hardlink`: create hardlinks to share inodes; limited to the same filesystem.
- `copy`: copy bytes into the instance; best for isolation or when you need to modify files.

Mode is selected via `--data-cache-mode off|symlink|hardlink|copy`.

## Building and using cache entries

- On `fetch` or `verify`:
  - If a valid cache entry is found: materialize from cache using the selected mode.
  - If missing/invalid or `--force-data-cache` is set: acquire `.verify.lock`, build the cache in `<cache_dir>/data`, compute content hash/size, write `.meta.json`, and release the lock, then materialize.
- On `check`: if a cache mode other than `off` is selected, the command reports cache presence and validity but does not materialize.

## CLI flags that control caching

- `--data-cache-mode off|symlink|hardlink|copy`
  - Controls whether caching is used and how cache content is materialized into the instance.
- `--force-data-cache`
  - Rebuilds cache entries even if a valid `.meta.json` exists.
- `--base-dir DIR`
  - Sets the root for `flo_data_cache`. For `run` and `instance create`, the same option is forwarded to data operations, keeping cache co-located with your run directories.

## Used by run/execute and data commands

- `floability run` and `floability instance create` pass their `--base-dir`, `--data-cache-mode`, and `--force-data-cache` options into the data operation phase when a `--data-spec` is provided.
- `floability data --mode fetch|verify` also uses the cache according to the same flags and then stages content under `<backpack_root>/workflow/...` or an overridden `target_prefix`.

## Best practices and notes

- Prefer `symlink` mode for read-only workflows; it’s fast and space efficient.
- Use `copy` if tools modify files in-place.
- `hardlink` requires target and cache on the same filesystem.
- Cache directories are safe to share across runs and are content-addressed by key.
- The lock file (`.verify.lock`) prevents duplicate work during concurrent builds.
