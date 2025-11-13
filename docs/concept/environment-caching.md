# Environment caching and setup

Floability optimizes environment setup by caching extracted Conda environments and tarball packs in a shared location and preferring fast clone operations when possible.

## Shared cache layout

Under the chosen base directory (e.g., `--base-dir .`), Floability maintains:

- flo_common_env/extracted_envs/env_<hash>/ — an extracted Conda environment built from the environment YAML
- flo_common_env/tarballs/env_<hash>.tar.gz — a conda-pack archive of the same environment

The `<hash>` is computed from a normalized environment YAML content. Both manager and worker environments can be produced this way; the worker env excludes Jupyter and other manager-only dependencies.

## Manager and worker environments

- Manager environment (from `--environment`): includes Python, Jupyter, ndcctools, cloudpickle (plus your dependencies). Extracted into `<instance>/current_conda_env` for use by Jupyter and execution.
- Worker environment (from `--worker-environment`): a pack path recorded in instance metadata and passed to `vine_factory` as `--poncho-env`. When unspecified, workers fall back to the manager environment pack. If neither is present, workers run with the system Python.

For how worker packs are used at runtime, see [Concepts → Workers](./workers.md).

## Environment variables

Floability sets manager-specific variables inside the per-instance environment after clone/extraction (e.g., manager name and ports). It does not inject them into the base YAML, which keeps the cache reusable across instances.

## Performance tracking

When `--measure-performance` is enabled, environment creation, packing, extraction, and cloning steps are timed, and pack sizes are recorded in the metrics directory.
