# Floability Data Reference

This page documents the Floability data spec (data.yml), the `floability data` command, and how profiles interact with `run` and `execute`.

## Quick contract


- **Inputs**: a YAML data spec file (`data.yml`) with one or more profiles (`data_profiles`), each having a `data` list and optional `policy`.

- **Outputs**: files staged into the workflow area (by default under `<backpack_root>/workflow/...`) and verification summaries on stdout.

- **Error modes**: missing sources, checksum/size mismatch, network failures, permission errors when writing targets.

- **Success criteria**: requested files exist at target and integrity checks pass (per `verification_type`).


## How to create a basic data.yml

Minimal example (only required fields):

```yaml
data_profiles:
  local_data:
    data:
      - source: backpack://data/sample-data.csv
        target_location: data/sample-data.csv
```

What this means:


- Declares a profile `local_data` with one item.

- The item uses a backpack-relative source (`backpack://...`).

- `target_location` is relative to `<backpack_root>/workflow/` by default.

Add integrity (`expected_size`, `checksum`) later to use `verify`.

## A more complete example (checksums, multiple profiles, policy)

Same data item across two profiles; only the source differs. Switch via `--data-profile`.

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
      verification_type: strict
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
        # target_prefix: /abs/path/to/staging
```

Notes:


- Profiles represent strategies/environments; the staged target and integrity values are identical.

- `verification_type: strict` requires a checksum to be present and match. Without checksum, prefer `size_only` and set `expected_size`.

- `run_operation` hints what `floability run` should do when `--data-spec` is provided (`fetch` for dev, `verify` for prod).


## CLI: `floability data` — overview

The `data` command uses `--mode` to choose behavior:


- `check`: metadata-only (existence, size if provided). No writes.

- `fetch`: download/copy sources to targets.

- `verify`: fetch as needed, then integrity-check (checksum/size) per policy.

Examples:

```sh
floability data --data-spec example/cms-physics-dv5/data/data.yml --mode check
floability data --data-spec example/cms-physics-dv5/data/data.yml --mode fetch --data-profile backpack-data --verbose
floability data --data-spec example/cms-physics-dv5/data/data.yml --mode verify --backpack . --force-fetch
```

### All available options


- `--mode` one of `check`, `fetch`, `verify` (default: `check`)

- `--data-spec` path to YAML spec

- `--backpack` backpack root for resolving `backpack` sources (default: `.`)

- `--check-details` print per-item metadata details (check mode)

- `--verbose` increase logging verbosity

- `--force-fetch` overwrite targets if they exist

- `--data-profile` override YAML `default_profile`

- `--data-cache-mode` one of `off|symlink|hardlink|copy` (default varies by command)
  - Controls whether cached data is used and how it is materialized into the instance.

- `--force-data-cache` force rebuild of cache entries even if a valid cache exists

- `--base-dir` set cache root (and run directories for run/instance flows); cache lives at `<base-dir>/flo_data_cache`

### How `--data-spec` and `--backpack` are resolved


- Both provided: used as given.

- Only `--backpack`: spec inferred at `<backpack>/data/data.yml`.

- Only `--data-spec`: if spec parent is `data`, backpack is its parent’s parent; otherwise backpack is the spec’s parent.

## YAML spec: top-level structure (human-readable)

Top-level keys (schema 1.0):


- `schema_version` optional (default `1.0`). Informational.

- `default_profile` optional (defaults to first in `data_profiles`).

- `data_profiles` required. Map of profile name → data profile.

Profile schema:


- `policy` optional

  - `retry_attempts` int ≥ 0 (default 0)

  - `timeout` seconds (int ≥ 0)

  - `size_tolerance_bytes` int ≥ 0 (default 0)

  - `run_operation` `check|fetch|verify` (hint)

  - `verification_type` `strict|size_only` (default `size_only`)


- `data` required — list of items

Item schema:


- `name` optional (string)

- `source_type` optional; inferred from `source` if omitted (`backpack`, `fs`, `pelican`, `http`, `osdf`)

- `source` required if `sources` not provided

- `sources` optional list (fallbacks). Each may have `source_type` and must have `source`.

- `target_location` required (string). Relative resolves under `<backpack_root>/workflow`.

- `target_prefix` optional (string). Overrides default staging prefix.

- `expected_size` optional (int). Compared with `size_tolerance_bytes`.

- `checksum` optional (string). Recommend `sha256:<hex>`.

- `content_type` optional (string). Reserved.

Example item (remote/pelican):

```yaml
- name: diboson_zz_6
  source_type: pelican
  source: pelican://disc-head-002.crc.nd.edu:443/nd/.../nano_mc2017_6.root
  expected_size: 190634
  checksum: sha256:4c976188f...
  target_location: data/samples/diboson/zz/nano_mc2017_6.root
```

Notes on `source` forms:


- `backpack`/`fs` use local paths. Backpack relative paths resolve against `--backpack`.

- `backpack://path/to/file` is normalized to `source_type: backpack` with prefix stripped.

- Remote schemes (`pelican://`, `http(s)://`) are handled by the respective helpers.

### Source type examples

```yaml
# backpack
- name: local_csv
  source_type: backpack
  source: data/local.csv
  target_location: data/local.csv

# fs
- name: shared_parquet
  source_type: fs
  source: /data/shared/sample.parquet
  target_location: data/shared/sample.parquet

# http
- name: http_json
  source_type: http
  source: https://example.org/data/sample.json
  expected_size: 2048
  target_location: data/http/sample.json

# pelican
- name: pelican_root
  source_type: pelican
  source: pelican://server.example.org:443/nd/datasets/sample-1.root
  expected_size: 100000
  checksum: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  target_location: data/pelican/sample-1.root

# osdf
- name: osdf_txt
  source_type: osdf
  source: osdf://osdf.example.org:443/nd/datasets/readme.txt
  expected_size: 128
  target_location: data/osdf/readme.txt
```

## Multi-source / fallback behavior

An item may include multiple sources using `sources` (attempted in order):

```yaml
- name: bigfile
  sources:
    - pelican://server/large
    - backpack://data/cache/large
  expected_size: 1000000
  checksum: sha256:...
  target_location: data/bigfile
```

## How data profile is used in `run` / `execute`

`floability run` and `execute` accept `--data-spec`, `--backpack` (or `--backpack-root`) and `--data-profile`. If `--data-spec` is provided, a fetch commonly occurs early (guided by the profile policy).

```sh
floability run --backpack . --data-spec example/cms-physics-dv5/data/data.yml --data-profile backpack-data
```

If `--data-profile` is omitted, the spec’s `default_profile` (or first profile) is used.

## Cache layout and modes

Floability caches data artifacts to avoid repeated downloads/copies across runs. The cache is content-addressed by a key derived from a normalized artifact spec (sources, checksum, size, etc.).

- Cache root: `<base-dir>/flo_data_cache/`
- Entry directory: `<base-dir>/flo_data_cache/<cache_key>/`
- Contents:
  - `data/` — cached bytes (file or directory tree)
  - `.meta.json` — metadata with content SHA-256 and size
  - `.verify.lock` — build lock (present only during build/verify)

Materialization into the instance target path uses the selected mode:

- `symlink` (default): link from cache to target; fast and space-efficient
- `hardlink`: share inodes (same filesystem only)
- `copy`: copy bytes for isolation/mutation

Controls (passed to both `floability data` and the run/instance data phase):

- `--data-cache-mode off|symlink|hardlink|copy`
- `--force-data-cache`
- `--base-dir DIR`

See Concepts → Data caching for a deeper dive.

## Formal schema (JSON Schema)

Use this to validate `data.yml` with standard tooling.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Floability data spec",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "schema_version": { "type": ["string", "number"], "default": "1.0" },
    "default_profile": { "type": "string" },
    "data_profiles": {
      "type": "object",
      "minProperties": 1,
      "additionalProperties": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "policy": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "retry_attempts": { "type": "integer", "minimum": 0, "default": 0 },
              "timeout": { "type": "integer", "minimum": 0 },
              "size_tolerance_bytes": { "type": "integer", "minimum": 0, "default": 0 },
              "run_operation": { "type": "string", "enum": ["check", "fetch", "verify"] },
              "verification_type": { "type": "string", "enum": ["strict", "size_only"], "default": "size_only" }
            }
          },
          "data": {
            "type": "array",
            "minItems": 1,
            "items": { "$ref": "#/definitions/dataItem" }
          }
        },
        "required": ["data"]
      }
    }
  },
  "required": ["data_profiles"],
  "definitions": {
    "dataItem": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "name": { "type": "string" },
        "source_type": { "type": "string", "enum": ["backpack", "fs", "pelican", "http", "osdf", "multi"] },
        "source": { "type": "string" },
        "sources": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "source_type": { "type": "string", "enum": ["backpack", "fs", "pelican", "http", "osdf"] },
              "source": { "type": "string" }
            },
            "required": ["source"]
          }
        },
        "target_location": { "type": "string" },
        "target_path": { "type": "string" },
        "target_prefix": { "type": "string" },
        "expected_size": { "type": "integer", "minimum": 0 },
        "checksum": { "type": "string", "pattern": "^(sha256|md5|sha1):[A-Fa-f0-9]{8,}$" },
        "content_type": { "type": "string" }
      },
      "oneOf": [ { "required": ["source"] }, { "required": ["sources"] } ],
      "required": ["target_location"]
    }
  }
}
```

## Implementation notes


- Local copies for `fs`/`backpack` use `fs_file_utils` helpers (resume/atomic publish). `--backpack` supplies the root; backpack-relative paths resolve against it.

- `verify` may fetch then validate checksum/size and report per-item results and a summary.

- `check` calls metadata helpers only and does not write targets.

## Troubleshooting


- Missing/incorrect `--backpack`: backpack-relative sources won’t resolve.

- Permissions: ensure the run user can write to `<backpack_root>/workflow`.

- Partial downloads: use `--force-fetch` to overwrite.

- Checksum/size mismatches: verify which check failed and inspect the staged file.

## Recommended testing checklist


- Create a small `data.yml` with one `backpack` item and one remote item.

- Run `floability data --mode check` to confirm metadata resolution.

- Run `floability data --mode fetch --verbose --backpack .` to stage local items.

- Run `floability data --mode verify` to validate checksum/size flows.
## Floability Data Reference

This document describes the Floability data capability: the YAML data spec format, the `floability data` command, available CLI options, and how to use data profiles with `run` and `execute`.

## Quick contract

- Inputs: a YAML data spec file (`data.yml`) containing one or more data profiles (`data_profiles`), each with a list of data items and a per-profile policy.
- Outputs: files staged into the run/workflow area (by default under `<backpack_root>/workflow/...`), and verification/summary reports printed to stdout.
- Error modes: missing sources, checksum/size mismatch, network errors, permission errors when writing to target.
- Success criteria: requested files exist at target, and (for `verify`) integrity checks (checksum/size) pass.


## How to create a basic data.yml

Minimal example (only required fields):

```yaml
data_profiles:
  local_data:
    data:
      - source: backpack://data/sample-data.csv
        target_location: data/sample-data.csv

```

What this spec means:

- This file declares a single data profile named `local_data`.
- It contains one data item whose source is inside the backpack (`backpack://...`).
- The `source` path is relative to your backpack root (`data/sample-data.csv`).
- The file will be staged to `target_location` relative to `<backpack_root>/workflow/` by default.

You can keep the basic example minimal. For integrity checks (optional), you can later add `expected_size` and/or `checksum` and run in `verify` mode to ensure the staged file matches.

### A more complete example (checksums, multiple profiles, policy)

```yaml
schema_version: 1.0
default_profile: local_data

data_profiles:
  local_data:
    policy:
      retry_attempts: 0
      timeout: 30
      size_tolerance_bytes: 10
      run_operation: fetch           # default action during `floability run` when data_spec is present
      verification_type: strict      # strict = require checksum match when provided
    data:
      - name: sample_data_small
        source_type: backpack
        source: data/sample-data.csv
        expected_size: 43210
        checksum: sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
        target_location: data/sample-data.csv

  remote_data:
    policy:
      retry_attempts: 2
      timeout: 60
      size_tolerance_bytes: 64
      run_operation: verify          # for production, verify integrity before running
      verification_type: strict
    data:
      - name: big_sample
        # Try remote first, then fallback to a local backpack cache
        sources:
          - source_type: pelican
            source: pelican://server.example.org:443/datasets/big/sample-1.root
          - source_type: backpack
            source: data/cache/sample-1.root
        expected_size: 1000000
        checksum: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
        target_location: data/remote/big/sample-1.root
        # Optionally override where targets get staged
        # target_prefix: /abs/path/to/staging
```

Notes:
- Use data profiles to switch between different data sets (e.g., a small local test set vs. a full remote dataset). Select profiles via `--data-profile`.
- `verification_type` suggestion: `strict` requires checksum match when provided; a looser option (e.g., `size_only`) would validate by size if no checksum is available. If neither size nor checksum is present, verification falls back to existence checks.
- `run_operation` sets what `floability run` will do by default when a `--data-spec` is provided (commonly `fetch` for local dev, `verify` for production).

Notes:
- `schema_version` is currently `1.0`.
- `default_profile` names the data profile used when no profile override is supplied.
- `data_profiles` maps profile name → data profile object.

Each profile contains a `policy` block and a `data` list. The `policy` configures retries, timeouts and allowed size tolerance. The `data` list defines individual items (see below).

## CLI: `floability data` — overview

The `data` command is a unified entry point for data operations. It uses `--mode` to pick behavior:

- `check`: validates that each data source is reachable/accessible and, if `expected_size` is provided, that the reported size matches. It does not fetch or modify targets. This is useful when your application downloads data itself, but Floability should still validate the sources up-front so workflows won't fail later.
- `fetch`: downloads or copies sources into target staging locations.
- `verify`: fetches as needed and then validates according to the profile's `verification_type` policy. With `strict`, a checksum is required and must match; with `size_only` (the default), verification checks size when provided, otherwise falls back to existence.

Examples:

- Check metadata only using the spec in the current directory:

```sh
floability data --data-spec example/cms-physics-dv5/data/data.yml --mode check
```

- Fetch (copy) files using a particular data profile:

```sh
floability data --data-spec example/cms-physics-dv5/data/data.yml --mode fetch --data-profile local_data --verbose
```

- Verify (download + integrity checks):

```sh
floability data --data-spec example/cms-physics-dv5/data/data.yml --mode verify --backpack . --force-fetch
```

When using `run` or `execute`, Floability will also consult the `--data-profile` value (see section below) and may fetch data early during `run` if a `--data-spec` is provided.

## All available CLI options (for `floability data`)

The `data` command accepts the following flags:

- `--mode` (choices: `check`, `fetch`, `verify`), default: `check`.
- `--data-spec` Path to the YAML spec (e.g. `data/data.yml`).
- `--backpack` Path to the root of a Floability backpack (used to resolve `backpack` source_type or `backpack://` URIs). Default: `.` (current directory) unless inferred.
- `--check-details` (flag) Print per-item detailed metadata after summary (only meaningful for `check` mode; `--verbose` implies detailed output).
- `--verbose` (flag) Increase verbosity. When enabled, the command prints per-item progress, and `check` will emit details.
- `--force-fetch` (flag) Overwrite targets even if they already exist (useful to re-fetch, or when you suspect a corrupt local copy).
- `--data-profile` Profile name to override the YAML `default_profile`.

When `floability run` or `floability execute` are used, you can pass the same flags via the `--data-profile`, `--data-spec`, and `--backpack-root`/`--backpack` CLI args in those commands; they are forwarded into the data handling path.

### How `--data-spec` and `--backpack` are resolved

- Both provided: use both as given.
- Only `--backpack` provided: the data spec is inferred at `<backpack>/data/data.yml` (typical backpack layout). If missing, the command will report that the spec was not found.
- Only `--data-spec` provided: the backpack root is inferred from the spec path.
  - If the spec’s parent directory is literally named `data`, then `backpack_root = parent_of(data)` (i.e., two levels up from the spec file).
  - Otherwise, `backpack_root = spec_parent_dir`.

These same inference rules are used internally when verifying or fetching directly from a `data_spec` file.

## YAML spec: top-level structure and schema

Top-level keys (schema 1.0):

- `schema_version` (optional; default: `1.0`)
  - Informational marker. The current implementation does not branch on this.
- `default_profile` (optional; default: first key under `data_profiles`)
  - If omitted, the first profile defined in `data_profiles` is used.
- `data_profiles` (required)
  - Mapping of profile-name → data profile object.

Data profile object schema:

- `policy` (object, optional; default: `{}`)
  - `retry_attempts` (optional; integer, default: `0`)
    - Currently informational; not used by the built-in downloaders yet.
  - `timeout` (optional; integer seconds)
    - Currently informational; not used by the built-in downloaders yet.
  - `size_tolerance_bytes` (optional; integer, default: `0`)
    - Allowed absolute difference when comparing `expected_size`.
  - `run_operation` (optional; one of `check`, `fetch`, `verify`; effective default: `fetch`)
    - Guides higher-level automation; current `run` behavior always fetches when a data spec is present.
  - `verification_type` (optional; `strict` | `size_only`, default: `size_only`)
    - `strict`: checksum must be provided and must match. `size_only`: verify size when provided, otherwise existence.

- `data` (required)
  - List of data item objects (see below).

Data item schema (fields):

- `name` (optional; string; default: `"<unnamed>"`)
  - Identifier for the item. Auto-filled if omitted.
- `source_type` (optional; string; default: inferred from `source`)
  - Typical values: `backpack`, `fs`, `pelican`, `http`, `osdf`.
  - Inferred when omitted: `backpack://...` → `backpack`, `http(s)://...` → `http`, `pelican://` or `osdf://` → `pelican`, else `fs`.
- `source` (conditionally required)
  - Required when `sources` is not provided. Path/URL to the primary source.
- `sources` (optional; list)
  - Multi-source fallback; each entry may include `source_type` and `source`.
- `target_location` (required; string)
  - Relative or absolute path where the item will be staged. If relative, it’s resolved under `<backpack_root>/workflow` by default.
  - A legacy alias `target_path` is still accepted but is deprecated; prefer `target_location`.
- `target_prefix` (optional; string; default: `<backpack_root>/workflow`)
  - Absolute or relative prefix combined with the target path.
- `expected_size` (optional; integer)
  - Validated by `check`/`verify` with `size_tolerance_bytes`.
- `checksum` (optional; string)
  - `sha256:<hex>` recommended. Used by `verify`; required in `strict` mode.
- `content_type` (optional; string)
  - Reserved for future use; not enforced by current `verify`.

Example item (remote/pelican):

```yaml
- name: diboson_zz_6
  source_type: pelican
  source: pelican://disc-head-002.crc.nd.edu:443/nd/.../nano_mc2017_6.root
  expected_size: 190634
  checksum: sha256:4c976188f...
  target_location: data/samples/diboson/zz/nano_mc2017_6.root
```

Notes on `source` forms:
- `backpack` or `fs` source types use local filesystem paths. Relative paths (not starting with `/`) are resolved against the `--backpack`/`--backpack-root` value when `backpack` is involved; otherwise they are resolved relative to the current working directory.
- Lightweight scheme: `backpack://path/to/file` will be detected during normalization and treated as `source_type: backpack` with the prefix stripped.
- Remote schemes like `pelican://`, `http://`, `https://` are handled by the matching helpers (e.g. `pelican_file_utils`, `http_file_utils`).

### Source type examples

Minimal examples for each supported `source_type` with simple filenames:

```yaml
# backpack: file lives inside the backpack layout
- name: local_csv
  source_type: backpack
  source: data/local.csv
  target_location: data/local.csv

# fs: file on the local filesystem (absolute path or relative to CWD)
- name: shared_parquet
  source_type: fs
  source: /data/shared/sample.parquet
  target_location: data/shared/sample.parquet

# http: file downloadable over HTTP/HTTPS
- name: http_json
  source_type: http
  source: https://example.org/data/sample.json
  expected_size: 2048
  target_location: data/http/sample.json

# pelican: file available via a Pelican/OSDF endpoint
- name: pelican_root
  source_type: pelican
  source: pelican://server.example.org:443/nd/datasets/sample-1.root
  expected_size: 100000
  checksum: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  target_location: data/pelican/sample-1.root

# osdf: OSDF endpoint (alias or separate helper, depending on deployment)
- name: osdf_txt
  source_type: osdf
  source: osdf://osdf.example.org:443/nd/datasets/readme.txt
  expected_size: 128
  target_location: data/osdf/readme.txt
```

## Multi-source / fallback behavior

An item can include multiple sources using `sources` (a list). Floability will attempt sources in order until one succeeds. This supports fallback from remote → cached local backpack → alternative mirrors.

Example:

```yaml
- name: bigfile
  sources:
    - pelican://server/large
    - backpack://data/cache/large
  expected_size: 1000000
  checksum: sha256:...
  target_location: data/bigfile
```

## How data profile is used in `run` / `execute`

When you start a run via `floability run` or `floability execute`, the CLI accepts `--data-spec`, `--backpack` (or `--backpack-root`) and `--data-profile`. If `--data-spec` is provided, Floability will (by default) perform a fetch early in the `run` path to stage required data. That early fetch will respect `--data-profile` if provided and will behave identically to invoking `floability data` with the same flags.

Examples:

```sh
# Start a run and force selection of the 'local_data' profile for data operations
floability run --backpack . --data-spec example/cms-physics-dv5/data/data.yml --data-profile local_data
```

If `--data-profile` is omitted, the spec's `default_profile` is used (if present). If no default is present and no profile is supplied, the first profile defined in `data_profiles:` is used.

## Implementation notes (useful for developers)

- Local file copies for `fs`/`backpack` use the `fs_file_utils` helpers for file-level copy (which supports resume/atomic publish) and may use a directory-copy helper for directories. The CLI provides `--backpack` to supply the backpack root path; relative `backpack` sources are resolved against that root.
- The `verify` flow will `fetch` (copy or download) when the target is missing or when `--force-fetch` is supplied, then compute checksum/size comparisons and report pass/fail per-item and in a summary.
- The `check` flow is metadata-only: it calls remote/local metadata helpers to determine existence and size; it does not write any target files.

## Edge cases and common troubleshooting

- Missing `--backpack` or incorrect `backpack` path: relative `backpack` sources won't be found. Either make the spec use absolute paths, or pass `--backpack` with the correct path.
- Permissions: ensure the Floability run user can write to the target staging area (e.g. `<backpack_root>/workflow`).
- Partial downloads: file-copy helpers attempt resumable or atomic publish for files; use `--force-fetch` to overwrite problematic files.
- Checksum/size mismatches: verify prints which check failed (checksum vs size). Investigate by manually inspecting the staged file and comparing checksums.

## Recommended testing checklist

- Create a small `data.yml` with one `backpack` item and one remote item.
- Test `floability data --mode check` to ensure metadata resolution works.
- Test `floability data --mode fetch --verbose --backpack .` to stage local items.
- Test `floability data --mode verify` to validate checksum/size flows.

## TODOs and future improvements

- Formal schema or JSON Schema file to validate `data.yml` before running.
- Add unit tests for `fs_file_utils` directory-copy helper and the `data_handler` integration tests that exercise `local_data` and `nd_data` profiles.
- Document `target_prefix` per-item overrides and publish the canonical default resolution rule.

## Appendix: Full YAML example (from example/cms-physics-dv5)

See `example/cms-physics-dv5/data/data.yml` for a real-world example containing two data profiles: `local_data` (backpack sources) and `nd_data` (pelican remote sources).

----

If anything in this doc is unclear or you want a machine-parsable JSON Schema, I can add a `data_schema.json` and a validator hook that runs at CLI startup.
