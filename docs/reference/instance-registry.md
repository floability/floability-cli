# Instance Registry
Floability maintains global instance and recent-base registries. The instance
registry supports stable short names; the base registry makes `instance latest`
consistent across multiple storage locations.

## Location

Registry file location depends on OS:

- Linux/macOS:
  - `$XDG_DATA_HOME/floability/instances.json` (if `XDG_DATA_HOME` is set), or
  - `~/.local/share/floability/instances.json`
- Windows:
  - `%APPDATA%/Floability/instances.json` (if `APPDATA` is set), or
  - `~/Floability/instances.json`

The same directory contains `base-directories.json`, which retains the 10 most
recent base directories used by accepted `run` or `execute` attempts.

The directory is created if missing.

## Schema (v1)

```
{
  "schema_version": 1,
  "instances": {
    "short_name": {
      "path": "/abs/path/to/instance",
      "base_dir": "/abs/path/to/base",
      "created_at": "2025-11-13T12:34:56Z",
      "last_run_at": "2025-11-14T12:34:56Z",
      "last_seen": "2025-11-14T12:34:56Z",
      "manager_name": "floability-uuid",
      "tags": []
    }
  }
}
```

Notes:

- `schema_version` is currently `1`.
- Timestamps are UTC ISO strings ending in `Z`.
- `last_run_at` is `null` until an accepted `run` or `execute` attempt starts.
- Registry updates are locked and saved atomically using a temporary file in
  the same directory, then replaced.

The recent-base registry has this shape:

```json
{
  "schema_version": 1,
  "base_directories": [
    {
      "path": "/abs/path/to/base",
      "last_used_at": "2025-11-14T12:34:56Z"
    }
  ]
}
```

Entries are sorted by `last_used_at` when read; their JSON array order is not
treated as authoritative.

## Behavior

- Register on creation:
  - `floability instance create` and new-instance `floability run` flows register the instance.
  - If `--name` is provided, Floability sanitizes it by replacing spaces with `_`.
  - If the name already exists, Floability appends `-2`, `-3`, and so on.
  - If the same absolute path is already registered, Floability reuses the existing short name.
- Resolve:
  - Commands that accept `--instance` can use either a short name or a direct instance path.
  - If `--instance` is an existing directory path, it is used directly.
- Run history:
  - Every accepted `run` or `execute` attempt updates `last_run_at`, `last_seen`,
    and its base-directory timestamp.
  - `instance create` registers the instance but does not mark it as run.
- Latest:
  - Without `--base-dir`, Floability selects the most recently run instance in
    the most recently used base directory.
  - An explicit `--base-dir` restricts selection to that existing directory and
    does not change which base is current.
- Prune:
  - Registry reads safely prune confirmed-missing instance and base paths.
  - Paths that cannot be checked because of an access or filesystem error are
    retained rather than guessed missing.
- Status:
  - Listing is global across bases, sorted by `last_run_at`, and derives live
    status from disk (`exists`) and lock state (`running`).

## Recovery and Corruption Handling

- If a registry file is missing, Floability starts with an empty registry.
- Legacy instance entries are migrated conservatively. A completed legacy run
  can supply `last_run_at`; creation alone cannot.
- If registry JSON is unreadable or malformed, Floability preserves the file,
  reports the error, and returns a nonzero result rather than silently replacing
  history.
- If one path is confirmed missing, maintenance removes that entry. Access
  errors retain the entry for a later retry.

If you suspect corruption, remove or rename the registry file and recreate entries by running `floability instance create` or `floability run`.

## Related commands

- `floability instance create --backpack PATH [--name NAME]`
- `floability instance list [--show-paths] [--all-details]`
- `floability run --instance NAME_OR_PATH`
- `floability workers start --instance NAME_OR_PATH`
- `floability workers stop --instance NAME_OR_PATH`
- `floability workers status --instance NAME_OR_PATH`
- `floability instance stop NAME_OR_PATH`
