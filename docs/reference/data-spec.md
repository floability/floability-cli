# Data Specification Reference

This page documents the `data.yml` format used by Floability.

## Matrix Example and Impact

From [example/matrix-multiplication/data/data.yml](../../example/matrix-multiplication/data/data.yml):

```yaml
default_profile: default

data_profiles:
  default:
    data:
      - source: "backpack://data/matrix_A.npy"
        target_location: "data/matrix_A.npy"
      - source: "backpack://data/matrix_B.npy"
        target_location: "data/matrix_B.npy"
```

Impact:

- Before your notebook runs, Floability resolves these files and stages them in the workflow environment.
- Your code can read predictable local paths (for example `data/matrix_A.npy`) without source-specific logic.
- The same workflow can switch to another profile later (for example S3 or Pelican) without notebook changes.

## Top-Level Structure

A data spec supports both modern and legacy top-level profile keys:

```yaml
schema_version: 1.0                # optional
default_profile: default            # optional

# Preferred key
data_profiles:
  default:
    policy: ...                     # optional
    data: ...                       # required per profile

# Legacy key (still supported)
profiles:
  default:
    policy: ...
    data: ...
```

Notes:

- `data_profiles` is preferred in new files.
- `profiles` is kept for backward compatibility.
- Floability uses `default_profile` when present; otherwise it falls back to the first profile.

## Profile Schema

Each profile has:

- `policy` (optional): operation and verification behavior.
- `data` (required): list of data items.

### Policy Keys

Supported policy keys and defaults:

- `run_operation`: `fetch` | `check` | `verify` (default `fetch`)
- `verification_type`: `size_only` | `strict` (default `size_only`)
- `retry_attempts`: integer (default `0`)
- `timeout`: integer seconds (default `30`)
- `size_tolerance_bytes`: integer (default `10`)

Example:

```yaml
policy:
  run_operation: fetch
  verification_type: strict
  retry_attempts: 2
  timeout: 60
  size_tolerance_bytes: 64
```

## Data Item Schema

Each item in `data:` must include:

- `source` or `sources`
- `target_location` (or legacy `target_path`)

Supported item keys:

- `name` (optional)
- `source` (string)
- `sources` (list of source entries)
- `source_type` (optional, inferred if omitted)
- `source_object_type` (optional; for object/directory semantics where supported)
- `target_location` (preferred)
- `target_path` (legacy alias)
- `target_prefix` (optional; absolute staging prefix override)
- `expected_size` (optional)
- `checksum` (optional; typically `sha256:<hex>`)
- `content_type` (optional; reserved)

### Single-source Item

```yaml
- name: sample_csv
  source: backpack://data/samples/sample.csv
  target_location: data/samples/sample.csv
  expected_size: 43210
  checksum: sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

### Multi-source Fallback Item

When `sources` is provided, entries are attempted in order until one succeeds.

```yaml
- name: file_a
  sources:
    - source: pelican://server.example.org/path/file_a.bin
    - source: s3://my-bucket/file_a.bin
    - source: backpack://data/file_a.bin
  target_location: data/file_a.bin
```

For each `sources[]` entry:

- `source` is required.
- `source_type` is optional.
- `source_object_type` is optional.

## Source Types

Floability supports these source types in current implementation:

- `backpack`
- `fs`
- `http`
- `s3`
- `pelican`
- `multi` (for `sources` aggregation)

Inference behavior:

- `backpack://...` is treated as `backpack`.
- `http://...` and `https://...` are treated as `http`.
- `s3://...` is treated as `s3`.
- `osdf://...` is currently handled via Pelican logic.

## Minimal Working Spec

```yaml
data_profiles:
  local_data:
    data:
      - source: backpack://data/sample.csv
        target_location: data/sample.csv
```

## Complete Example

```yaml
schema_version: 1.0
default_profile: backpack-data

data_profiles:
  backpack-data:
    policy:
      retry_attempts: 0
      timeout: 30
      size_tolerance_bytes: 10
      run_operation: fetch
      verification_type: strict
    data:
      - name: sample_csv
        source_type: backpack
        source: data/samples/sample.csv
        expected_size: 43210
        checksum: sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
        target_location: data/samples/sample.csv

  pelican-data:
    policy:
      retry_attempts: 2
      timeout: 60
      size_tolerance_bytes: 64
      run_operation: verify
      verification_type: size_only
    data:
      - name: sample_csv
        sources:
          - source_type: pelican
            source: pelican://server.example.org:443/datasets/samples/sample.csv
          - source_type: backpack
            source: data/samples/sample.csv
        expected_size: 43210
        checksum: sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
        target_location: data/samples/sample.csv
```

## CLI Integration

### `floability data`

```bash
floability data --mode check --data-spec <path-to-data.yml>
```

Supported options:

- `--mode check|fetch|verify` (default `check`)
- `--data-spec`
- `--backpack`
- `--check-details`
- `--verbose`
- `--force-fetch`
- `--data-profile`
- `--data-cache-mode off|symlink|hardlink|copy` (default `off`)
- `--data-cache-dir`
- `--force-data-cache`
- `--fingerprint-mode meta|sample|strict` (default `meta`)
- `--base-dir`

### `floability run` / `floability execute`

These commands also consume data-spec options (including `--data-spec`, `--data-profile`, and cache flags). In these flows, operation defaults to profile `run_operation` with fallback to `fetch`.

## Caching Behavior

Cache controls:

- `--data-cache-mode`: `off`, `symlink`, `hardlink`, `copy`
- `--data-cache-dir`: explicit cache location
- `--force-data-cache`: rebuild cache entries

Default cache base when not overridden:

```text
<base-dir>/floability-data-cache
```

## Loader Validation Rules

The loader validates:

- Profile exists and has a non-empty `data` list.
- Every item has `source` or valid `sources`.
- Every item has `target_location` or `target_path`.
- Every `sources[]` entry defines `source`.

## Related Pages

- [CLI Commands](cli.md)
- [Compute Specification](compute-spec.md)
- [Manage Data](../how-to/manage-data.md)
