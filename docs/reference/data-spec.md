# Data Specification Reference

This page documents the `data.yml` format used by Floability.

## Matrix Example and Impact

The Matrix Multiplication backpack uses a profile of public CSV inputs. A
shortened entry looks like:

```yaml
schema_version: 1.0
default_profile: matrix_data
profiles:
  matrix_data:
    data:
      - name: matrix_dense_00
        source_type: http
        source: https://raw.githubusercontent.com/floability/backpack-test-data/refs/heads/main/matrix_200_200/matrix_dense_00.csv
        target_path: data/matrices/matrix_dense_00.csv
```

Impact:

- Before your notebook runs, Floability resolves these files and stages them in the workflow environment.
- Your code can read predictable local paths (for example
  `data/matrices/matrix_dense_00.csv`) without source-specific logic.
- The same workflow can switch to another profile later (for example S3 or Pelican) without notebook changes.

## Top-Level Structure

A data spec accepts both top-level profile keys. Current templates and examples
use `profiles`; `data_profiles` remains supported:

```yaml
schema_version: 1.0                # optional
default_profile: default            # optional

# Accepted key
data_profiles:
  default:
    policy: ...                     # optional
    data: ...                       # required per profile

# Used by current templates and examples
profiles:
  default:
    policy: ...
    data: ...
```

Notes:

- `data_profiles` and `profiles` are both accepted.
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
- `timeout`: integer seconds or null (default `null`)
- `size_tolerance_bytes`: integer (default `0`)

The generated data template explicitly uses `retry_attempts: 2`, `timeout:
60`, and `size_tolerance_bytes: 0`; those are template choices, not loader
defaults.

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

## Archive Post-Processing

Use `post_process` to safely extract a downloaded ZIP or TAR archive into its
`target_location`:

```yaml
- name: observations
  source: https://example.org/observations.zip
  target_location: data/observations
  post_process:
    operation: unzip
    limits:
      max_extracted_bytes: 1073741824
      max_entries: 10000
```

Supported operations are:

- `unzip` for ZIP archives; and
- `untar` for uncompressed TAR, TAR.GZ, TAR.BZ2, and TAR.XZ archives.

Extraction always creates a directory at `target_location`. The archive's
internal layout is preserved below that directory, whether the archive contains
one file, one top-level directory, or a nested directory tree.

The optional limits are checked before extraction:

- `max_extracted_bytes` limits the total declared uncompressed size; and
- `max_entries` limits the combined number of files and directories.

Floability rejects absolute paths, parent traversal, links, special files,
duplicate paths, and file/directory conflicts. It extracts into a unique
staging directory and publishes the completed result only after every member
has been written successfully. For multi-source items, another source is tried
only when acquiring the current source fails; an invalid archive does not
trigger source fallback.

When caching is enabled, the extracted directory is cached independently of
`target_location`, so one result can be materialized at different workflow
paths. Cache metadata records the operation implementation version and the
result's file count, directory count, and declared uncompressed size. Current
limits are checked again on every cache lookup.

Checksum validation is not yet supported for post-processed data. Floability
prints a warning and ignores a configured checksum for these items.

## Source Types

Floability supports these source types in current implementation:

- `backpack`
- `fs`
- `http`
- `s3`
- `pelican`
- `xrootd`
- `multi` (for `sources` aggregation)

Inference behavior:

- `backpack://...` is treated as `backpack`.
- `http://...` and `https://...` are treated as `http`.
- `s3://...` is treated as `s3`.
- `osdf://...` is currently handled via Pelican logic.
- `root://...` is treated as `xrootd`.

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
- `--cache-lookup-mode strict|local` (default `strict`)
- `--base-dir`

`check` is metadata-only and creates no instance. Direct `fetch` and `verify`
create a data-only instance under `--base-dir`, stage targets below its
`workflow/`, and update `latest_floability_instance`.

### `floability run` / `floability execute`

These commands also consume data-spec options (including `--data-spec`,
`--data-profile`, and cache flags). In these flows, operation defaults to
profile `run_operation` with fallback to `fetch`. Their cache default is
`symlink`; the direct `data` and `instance create` commands default to `off`.

## Caching Behavior

Cache controls:

- `--data-cache-mode`: `off`, `symlink`, `hardlink`, `copy`
- `--data-cache-dir`: explicit cache location
- `--force-data-cache`: rebuild cache entries
- `--cache-lookup-mode`: `strict` (specification plus source fingerprint) or
  `local` (artifact specification only)

Default cache base when not overridden:

```text
<base-dir>/floability-data-cache
```

When mode is `off`, Floability does not create or inspect this directory and
stages ordinary targets directly.

## Loader Validation Rules

The loader validates:

- Profile exists and has a non-empty `data` list.
- Every item has `source` or valid `sources`.
- Every item has `target_location` or `target_path`.
- Every `sources[]` entry defines `source`.
- Every `post_process` mapping selects `unzip` or `untar` and uses positive
  integer limits when limits are provided.

## Related Pages

- [CLI Commands](cli.md)
- [Compute Specification](compute-spec.md)
- [Manage Data](../how-to/manage-data.md)
