# Instance Registry

Floability maintains a global registry of instances so you can refer to them by short names instead of full paths.

## Location

On Linux/macOS, the registry is stored at:

- $XDG_DATA_HOME/floability/instances.json (if XDG_DATA_HOME is set), or
- ~/.local/share/floability/instances.json

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

The registry is saved atomically using a temporary file in the same directory for safety.

## Behavior

- Register on creation: New instances are registered with an auto-generated short name (or an optional explicit name).
- Resolve: Commands that accept `--instance` can take a short name; the CLI resolves it to a path.
- Touch: Using an instance updates its `last_seen` timestamp.
- Prune: Listing auto-prunes entries whose paths no longer exist.

## Related commands

- floability instance create --backpack PATH [--name NAME]
- floability instance list [--show-paths] [--all-details]
- floability run --instance NAME_OR_PATH
- floability workers start --instance NAME_OR_PATH
- floability instance stop NAME_OR_PATH
