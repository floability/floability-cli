from __future__ import annotations

import datetime
import re
from pathlib import Path

from floability import utils

FIXED_TIME = datetime.datetime(2026, 8, 22, 23, 19, 21, tzinfo=datetime.UTC)


def test_instance_name_is_readable_bounded_and_deterministic():
    name = utils._format_instance_directory_name(
        "fi_mobilenet-batch-inference",
        when=FIXED_TIME,
        random_suffix="a1b2c3d4",
    )

    assert name == "fi_mobilenet-batch_20260822-231921_a1b2c3d4"
    assert len(name.encode("utf-8")) <= utils.INSTANCE_DIRECTORY_MAX_BYTES


def test_long_unsafe_unicode_prefix_produces_portable_ascii_name():
    name = utils._format_instance_directory_name(
        "fi_Å very/long workflow 名称" * 20,
        when=FIXED_TIME,
        random_suffix="0123abcd",
    )

    assert re.fullmatch(
        r"fi_[a-z0-9-]{1,20}_20260822-231921_[a-f0-9]{8}",
        name,
    )
    assert len(name.encode("utf-8")) <= utils.INSTANCE_DIRECTORY_MAX_BYTES
    assert "/" not in name


def test_non_ascii_only_prefix_uses_workflow_fallback():
    name = utils._format_instance_directory_name(
        "fi_工作流",
        when=FIXED_TIME,
        random_suffix="0123abcd",
    )

    assert name == "fi_workflow_20260822-231921_0123abcd"


def test_instance_names_sort_by_utc_second_before_random_id():
    earlier = utils._format_instance_directory_name(
        "fi_example",
        when=FIXED_TIME,
        random_suffix="ffffffff",
    )
    later = utils._format_instance_directory_name(
        "fi_example",
        when=FIXED_TIME + datetime.timedelta(seconds=1),
        random_suffix="00000000",
    )

    assert earlier < later


def test_create_unique_directory_retries_a_collision(tmp_path, monkeypatch):
    collision = "fi_test_20260822-231921_00000000"
    available = "fi_test_20260822-231921_00000001"
    (tmp_path / collision).mkdir()
    generated_names = iter((collision, available))
    monkeypatch.setattr(
        utils,
        "_format_instance_directory_name",
        lambda _prefix: next(generated_names),
    )
    monkeypatch.setattr(utils.time, "sleep", lambda _seconds: None)

    created = Path(utils.create_unique_directory(tmp_path, prefix="fi_test"))

    assert created == tmp_path / available
    assert created.is_dir()
