# Manage Workflow Data

Floability reads `data/data.yml` to locate inputs and stage them at predictable
paths under an instance's `workflow/` directory. Keep source-specific download
logic in the data specification so the workflow itself can use ordinary local
paths.

See the [Data Specification Reference](../reference/data-spec.md) for the full
schema.

## Check a data profile

`check` inspects source metadata without downloading file contents:

```bash
floability data --mode check --backpack .
```

Use `--data-profile NAME` to select a profile other than `default_profile`, and
add `--check-details` for per-item metadata.

## Fetch or verify data

```bash
floability data --mode fetch --backpack . \
  --base-dir /scratch/$USER/floability

floability data --mode verify --backpack . \
  --base-dir /scratch/$USER/floability
```

`fetch` stages each target. `verify` also evaluates configured sizes and
checksums. When these direct commands fetch or verify without an existing
instance, Floability creates a data-only instance below `--base-dir` and
updates `latest_floability_instance`.

## Choose cache behavior

The direct `data` command defaults to no shared cache:

```bash
floability data --mode fetch --backpack . --data-cache-mode off
```

In `off` mode, Floability neither creates nor consults a shared data cache and
stages ordinary files. To reuse immutable inputs across instances, select a
materialization mode:

```bash
floability data --mode fetch --backpack . \
  --data-cache-mode symlink \
  --data-cache-dir /scratch/$USER/floability-data-cache
```

Available modes are:

- `symlink`: read-only shared-cache target with minimal extra disk usage;
- `hardlink`: shared inode, requiring cache and instance on one filesystem;
- `copy`: independent target copied from the cache; and
- `off`: direct staging with no shared-cache access.

`run` and `execute` default to `symlink`; direct `data` and `instance create`
default to `off`. Use `--force-data-cache` to rebuild an enabled cache entry.
Cache lookup defaults to `strict`, which matches both the item specification
and source fingerprint. `--cache-lookup-mode local` matches only the local
artifact specification.

## Use profiles for small and full inputs

Define a small default profile for smoke tests and a separate full profile for
production data:

```yaml
schema_version: 1.0
default_profile: smoke
profiles:
  smoke:
    data:
      - name: sample
        source: https://example.org/sample.csv
        target_location: data/sample.csv
  full:
    data:
      - name: complete
        source: s3://example-bucket/complete.csv
        target_location: data/complete.csv
```

Select the larger profile explicitly:

```bash
floability execute --backpack . --data-profile full
```

## Supported sources

Current source schemes are local backpack/filesystem paths, HTTP(S), S3,
Pelican/OSDF, and XRootD (`root://`). Remote protocols depend on their runtime
clients from the activated Floability environment. Before a large run, use a
small `check` or `verify` operation from the target site to confirm credentials,
network access, and expected checksums.

## Storage guidance

Large inputs and environment archives can exceed a home-directory quota. Put
all instances and default caches on project or scratch storage with
`--base-dir`, or move only the data cache with `--data-cache-dir`. Do not point
cleanup at an arbitrary directory: `floability tools clean` operates only on
Floability base directories selected explicitly or found in its recent-base
registry.
