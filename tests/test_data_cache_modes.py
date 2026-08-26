from pathlib import Path
from types import SimpleNamespace

import pytest

from floability.ops.data import run_data_command


def _make_local_data_backpack(root: Path) -> Path:
    backpack = root / "data-backpack"
    data_dir = backpack / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "input.txt").write_text("cache-mode-test\n", encoding="utf-8")
    (data_dir / "data.yml").write_text(
        """\
schema_version: 1.0
default_profile: local
profiles:
  local:
    data:
      - name: local_input
        source_type: backpack
        source: data/input.txt
        target_location: inputs/input.txt
""",
        encoding="utf-8",
    )
    return backpack


def _data_args(backpack: Path, base_dir: Path, cache_dir: Path, mode: str):
    return SimpleNamespace(
        mode="fetch",
        data_spec=None,
        backpack=str(backpack),
        check_details=False,
        verbose=False,
        force_fetch=False,
        data_profile=None,
        data_cache_mode=mode,
        data_cache_dir=str(cache_dir),
        force_data_cache=False,
        fingerprint_mode="meta",
        cache_lookup_mode="strict",
        base_dir=str(base_dir),
        instance=None,
        manager_name=None,
    )


@pytest.mark.parametrize(
    ("cache_mode", "cache_created", "target_is_symlink"),
    [
        ("off", False, False),
        ("symlink", True, True),
    ],
)
def test_data_fetch_respects_cache_mode(
    tmp_path: Path,
    cache_mode: str,
    cache_created: bool,
    target_is_symlink: bool,
):
    backpack = _make_local_data_backpack(tmp_path)
    base_dir = tmp_path / f"base-{cache_mode}"
    cache_dir = tmp_path / f"cache-{cache_mode}"

    assert run_data_command(
        _data_args(backpack, base_dir, cache_dir, cache_mode)
    )

    instance = (base_dir / "latest_floability_instance").resolve()
    assert instance.name.startswith("fi_floability-data_")

    target = instance / "workflow" / "inputs" / "input.txt"
    assert target.read_text(encoding="utf-8") == "cache-mode-test\n"
    assert target.is_symlink() is target_is_symlink
    assert cache_dir.exists() is cache_created


@pytest.mark.parametrize("operation", ["check", "fetch", "verify"])
def test_cache_off_never_creates_default_cache_directory(
    tmp_path: Path, operation: str
):
    backpack = _make_local_data_backpack(tmp_path)
    base_dir = tmp_path / operation
    args = _data_args(
        backpack,
        base_dir,
        base_dir / "floability-data-cache",
        "off",
    )
    args.mode = operation

    assert run_data_command(args)
    assert not (base_dir / "floability-data-cache").exists()
