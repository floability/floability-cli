from pathlib import Path

import pytest

from floability.data.data_handler import _resolve_target_path


@pytest.mark.unit
def test_resolve_target_path_honors_item_target_prefix_relative_to_backpack_root(
    tmp_path: Path,
):
    backpack_root = tmp_path / "backpack"
    target = _resolve_target_path(
        {
            "target_location": "data/file.txt",
            "target_prefix": "custom-output",
        },
        target_prefix=backpack_root / "workflow",
        backpack_root=backpack_root,
    )

    assert target == (backpack_root / "custom-output" / "data/file.txt").resolve()
