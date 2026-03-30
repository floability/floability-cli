# Instance Registry
Floability maintains a global registry of instances so you can refer to them by short names instead of full paths.

## Location

Registry file location depends on OS:

- Linux/macOS:
  - `$XDG_DATA_HOME/floability/instances.json` (if `XDG_DATA_HOME` is set), or
  - `~/.local/share/floability/instances.json`
- Windows:
  - `%APPDATA%/Floability/instances.json` (if `APPDATA` is set), or
  - `~/Floability/instances.json`

The directory is created if missing.

## Schema (v1)

```
{
  "schema_version": 1,
  "instances": {
    "short_name": {
      "path": "/abs/path/to/instance",
      "created_at": "2025-11-13T12:34:56Z",
      "last_seen": "2025-11-13T12:34:56Z",
      "manager_name": "floability-uuid",
      "tags": []
    }
  }
}
```

Notes:

- `schema_version` is currently `1`.
- Timestamps are UTC ISO strings ending in `Z`.
- The registry is saved atomically using a temporary file in the same directory, then replaced.

## Behavior

- Register on creation:
  - `floability instance create` and new-instance `floability run` flows register the instance.
  - If `--name` is provided, Floability sanitizes it by replacing spaces with `_`.
  - If the name already exists, Floability appends `-2`, `-3`, and so on.
  - If the same absolute path is already registered, Floability reuses the existing short name.
- Resolve:
  - Commands that accept `--instance` can use either a short name or a direct instance path.
  - If `--instance` is an existing directory path, it is used directly.
- Touch:
  - Reusing an instance through `floability run --instance ...` refreshes `last_seen`.
- Prune:
  - `floability instance list` prunes entries whose instance directory no longer exists.
- Status:
  - Listing derives live status from disk (`exists`) and lock state (`running`).

## Recovery and Corruption Handling

- If the registry file is missing, Floability starts with an empty in-memory registry.
- If the registry JSON is unreadable or malformed, Floability falls back to an empty registry.
- If one entry is stale (path removed), prune removes it without failing the whole listing.

If you suspect corruption, remove or rename the registry file and recreate entries by running `floability instance create` or `floability run`.

## Related commands

- `floability instance create --backpack PATH [--name NAME]`
- `floability instance list [--show-paths] [--all-details]`
- `floability run --instance NAME_OR_PATH`
- `floability workers start --instance NAME_OR_PATH`
- `floability workers stop --instance NAME_OR_PATH`
- `floability workers status --instance NAME_OR_PATH`
- `floability instance stop NAME_OR_PATH`
