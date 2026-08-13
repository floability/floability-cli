# Floability Reliability Rewrite TODO

This document records the agreed scope and priorities for stabilizing the
existing Floability execution flow before adding new features.

## Agreed behavior

- A workflow entrypoint can be a Jupyter notebook (`.ipynb`), Python script
  (`.py`), or shell script (`.sh`).
- Interactive execution starts JupyterLab. Batch execution runs the selected
  entrypoint to completion without JupyterLab.
- `--data-cache-mode off` genuinely disables the shared data cache and stages
  data directly in the instance.
- Shared, immutable Conda environments are the default. A private environment
  per instance remains an explicit option.
- `floability run` and `floability instance create` use the same instance
  preparation library and produce reusable instances with complete metadata.
- Audit is outside the current rewrite scope. Existing audit commands should
  remain wired to their current implementation unless main-interface changes
  require a small adapter.
- Generated build output, package metadata, virtual environments, and test
  caches must not be committed.

## CLI direction

Keep the existing public split for the reliability phase:

- `floability run`: interactive JupyterLab session
- `floability execute`: non-interactive batch execution

Both commands should call one internal execution operation with an explicit
mode. This preserves compatibility while removing duplicated behavior. Revisit
a public `floability run --mode ...` interface only after the execution model
and tests are stable.

## P0: Correct execution and shutdown

- [ ] Make interactive monitoring terminate when JupyterLab exits, including
      when workers are disabled.
- [ ] Ensure every success, failure, interrupt, and child-process exit follows
      one finalization path.
- [ ] Return reliable nonzero CLI exit codes for validation, setup, data,
      environment, worker, and workflow failures.
- [ ] Correct the invalid `floability run --execute` guidance.
- [ ] Define and test expected behavior when `vine_factory` exits before
      JupyterLab and when JupyterLab exits before `vine_factory`.
- [ ] Ensure subprocess groups are stopped without leaving factories, workers,
      Jupyter processes, or locks behind.

## P0: Repair worker lifecycle and locks

- [ ] Store and validate the `vine_factory` PID in the worker lock rather than
      the PID of the Floability CLI process.
- [ ] Make worker start acquire ownership safely and avoid a launch-before-lock
      race.
- [ ] Release worker locks during normal completion, failure, interrupt, and
      explicit stop.
- [ ] Detect and clean stale worker locks and stale `workers.json` state.
- [ ] Make `workers status` distinguish running, stopped, stale, and unknown.
- [ ] Add unit tests using fake subprocesses; do not require TaskVine or an HPC
      scheduler for these tests.

## P0: Unify instance preparation

- [ ] Extract one instance-preparation service used by both `run` and
      `instance create`.
- [ ] Give both flows the same backpack resolution, workflow copy, data
      staging, environment setup, metadata, registry, and failure cleanup.
- [ ] Persist enough metadata to reuse an instance and rebuild an evicted
      shared environment, including environment spec, environment strategy,
      environment packs, manager identity, ports, compute spec, and entrypoint.
- [ ] Keep `instance create` lower priority than the main run path, but prevent
      it from developing a separate implementation.
- [ ] Decide and document whether a partially prepared instance is retained or
      removed after each class of failure.

## P0: Implement the three entrypoint modes

- [ ] Introduce an entrypoint model containing type, resolved instance path,
      backpack-relative path, and selection source.
- [ ] Support `.ipynb`, `.py`, and `.sh` consistently in backpack validation,
      argument resolution, instance metadata, execution, and documentation.
- [ ] Make entrypoint selection deterministic when multiple candidates exist.
- [ ] Reject ambiguous auto-detection with an actionable message rather than
      depending on filesystem order.
- [ ] Keep an explicit entrypoint option that can select nested workflow files
      safely.
- [ ] Execute Python and shell entrypoints with streamed output and recorded
      exit status.
- [ ] Define interactive behavior for script entrypoints: open JupyterLab in
      the workflow directory without pretending the script was executed.
- [ ] Add focused tests for all entrypoint types and ambiguity cases.

## P1: Fix data-cache semantics

- [ ] Make cache mode `off` stage directly into the instance with no cache
      lookup, cache write, symlink, or forced override to `symlink`.
- [ ] Align `run`, `execute`, `instance create`, and `data` command defaults and
      option meanings.
- [ ] Standardize the cache root as
      `<base-dir>/floability-data-cache` and remove active `flo_data_cache`
      assumptions.
- [ ] Test direct staging separately from symlink, hardlink, and copy modes.
- [ ] Verify that mutable workflow inputs are not unexpectedly shared through
      symlinks or hardlinks.
- [ ] Reconcile `fingerprint-mode` and `cache-lookup-mode` with the actual
      implementation; remove obsolete choices rather than preserving no-op
      configuration.

## P1: Fix registry and instance state

- [ ] Derive registry `running` status from a live lock PID, not lock-file
      existence alone.
- [ ] Clean stale instance locks consistently during status, list, run, and
      stop operations.
- [ ] Make registry writes safe under concurrent CLI processes.
- [ ] Preserve stable short names when refreshing an already registered path.
- [ ] Add corruption, stale-path, stale-lock, and concurrency-oriented tests.

## P1: Harden shared environments

- [ ] Add per-environment locking around shared environment creation and
      packing.
- [ ] Validate both extracted environments and packs before treating them as
      cache hits.
- [ ] Make interrupted builds recoverable without manual deletion.
- [ ] Quote or avoid shell interpolation in post-install execution.
- [ ] Define how environment YAML changes, post-install script changes, and
      Floability-required package injection affect the cache key.
- [ ] Test cache reuse and eviction recovery without performing real Conda
      builds.

## P1: Align CLI contracts and errors

- [ ] Centralize argument validation and convert operational results into
      process exit codes at the CLI boundary.
- [ ] Ensure documented flags exist on the commands that consume them.
- [ ] Remove or explicitly deprecate legacy flags only after replacement paths
      and compatibility tests exist.
- [ ] Add parser and command-dispatch tests for every public command.
- [ ] Keep site defaults lower precedence than explicit CLI arguments and add
      tests for that rule.
- [ ] Reconcile ND port defaults with documentation.
- [ ] Either implement Anvil/Stampede3 detection or document that their
      settings must be supplied explicitly.

## P2: Documentation and repository hygiene

- [ ] Fill or remove the empty data-management and audit how-to pages.
- [ ] Update CLI, data, instance, worker, and deployment docs after behavior is
      covered by tests.
- [ ] Retire or rewrite draft documents that use obsolete schemas, commands,
      or cache paths.
- [ ] Remove stale `flo_instances/run_*` examples.
- [ ] Choose one authoritative packaging metadata source so dependencies and
      versions cannot drift between `pyproject.toml` and `setup.py`.
- [ ] Remove tracked generated artifacts after confirming they are not release
      inputs: `build/`, `floability.egg-info/`, virtual environments,
      `.pytest_cache/`, `__pycache__/`, and bytecode.
- [ ] Strengthen `.gitignore` for all generated artifacts above.
- [ ] Keep audit code unchanged during this phase except for necessary command
      adapters.

## Test strategy

- [ ] Establish a lightweight developer test environment whose dependencies
      match package metadata.
- [ ] Add unit tests around orchestration boundaries using fakes for Conda,
      Jupyter, `vine_factory`, and schedulers.
- [ ] Add local integration tests for backpack-to-instance preparation with a
      tiny notebook, Python script, shell script, and local filesystem data.
- [ ] Mark network tests and protocol-specific tests explicitly.
- [ ] Keep real TaskVine and scheduler checks as documented HPC smoke tests,
      not Dev Container unit-test requirements.
- [ ] Add a regression test for every execution-flow bug fixed in this list.

## Suggested implementation order

1. Add orchestration tests that expose shutdown, exit-code, lock, and registry
   failures.
2. Introduce the shared entrypoint and instance-preparation models without
   changing public CLI commands.
3. Repair finalization and worker locking.
4. Add `.sh` execution and deterministic entrypoint selection.
5. Correct cache-off behavior and unify data staging.
6. Harden environment caching and instance reuse.
7. Align documentation and remove confirmed generated/dead artifacts.

