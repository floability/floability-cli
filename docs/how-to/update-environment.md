# Update environment.yml from a Running Instance

After running a backpack, the conda environment that was actually built and used may differ from what is written in `software/environment.yml` — packages may have been resolved to different versions, transitive dependencies may have been pulled in, or you may have installed extra packages during an interactive session.

`floability backpack update-env` exports the environment that was used in a completed instance and writes the concrete, pinned versions back into the backpack.

> **See also:** [Create Your First Backpack](../getting-started/create-first-backpack.md) for how to set up the initial `environment.yml`.

## When to use this

- You ran a backpack and want to pin the exact versions that worked.
- You installed packages interactively during a session and want to capture them.
- You want to share a backpack with a fully reproducible environment spec.

## Prerequisites

- A completed instance (created by `floability run` or `floability instance create`).
- `conda` available on `PATH`.

## Two modes

### Full replacement (default)

Exports every package installed in the instance environment and uses that as the new dependency list. The backpack's `name` field and any floability-specific fields (e.g. `post_install_script`) are preserved; the `prefix` field from the export is dropped automatically.

```bash
floability backpack update-env --from-instance <name-or-path>
```

Run from inside the backpack directory, or pass an explicit path:

```bash
floability backpack update-env --from-instance fi_cms-physics_20260410104122618078 ./cms-physics
```

### Versions-only

Only updates the version of packages **already listed** in `environment.yml`. Structure, channels, package selection, `post_install_script`, and all other fields are left exactly as you wrote them.

```bash
floability backpack update-env --from-instance <name-or-path> --versions-only
```

Use this when your `environment.yml` is carefully curated and you only want to lock in the versions that were actually resolved, rather than expanding it to include every transitive dependency.

## Identifying the instance

Pass either a registered short name or a full path:

```bash
# by short name (from `floability instance list`)
floability backpack update-env --from-instance fi_cms-physics_20260410104122618078

# by path
floability backpack update-env --from-instance /path/to/floability-base-dir/fi_cms-physics_20260410104122618078
```

To find the latest instance quickly:

```bash
floability instance latest
floability backpack update-env --from-instance $(floability instance latest)
```

## What changes on disk

| File | Action |
|---|---|
| `software/environment.yml` | Overwritten with the updated spec |
| `software/old-environment.yml` | Backup of the previous `environment.yml` |

The backup lets you diff or roll back if needed:

```bash
diff software/old-environment.yml software/environment.yml
```

## Example: full replacement

Before (hand-written spec):

```yaml
name: cms-physics
channels:
  - conda-forge
dependencies:
  - python=3.10
  - numpy
  - coffea
  - pip:
    - fastjet==3.4.2.1
post_install_script: install_taskvine.sh
```

After running `update-env`:

```yaml
name: cms-physics
channels:
  - conda-forge
  - defaults
dependencies:
  - _libgcc_mutex=0.1
  - python=3.10.14
  - numpy=1.26.4
  - coffea=2024.4.0
  - ...
  - pip:
    - fastjet==3.4.2.1
    - coffea==2024.4.0
post_install_script: install_taskvine.sh
```

Note: `name` is preserved from the original backpack file, not taken from the conda export. `post_install_script` is also carried over.

## Example: versions-only

Before:

```yaml
name: cms-physics
channels:
  - conda-forge
dependencies:
  - python=3.10
  - numpy
  - coffea
  - pip:
    - fastjet==3.4.2.1
post_install_script: install_taskvine.sh
```

After running `update-env --versions-only` (only the version specs change):

```yaml
name: cms-physics
channels:
  - conda-forge
dependencies:
  - python=3.10.14
  - numpy=1.26.4
  - coffea=2024.4.0
  - pip:
    - fastjet==3.4.2.1
post_install_script: install_taskvine.sh
```

The package list stays exactly what you defined. Only the version strings are filled in from what was actually installed.

## Related pages

- [Backpacks](../concepts/backpacks.md)
- [Instances](../concepts/instances.md)
- [Create Your First Backpack](../getting-started/create-first-backpack.md)
