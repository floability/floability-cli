from __future__ import annotations

import argparse

import pytest

from floability.commands.argument_groups import add_execution_args
from floability.utils import (
    normalize_manager_ports,
    normalize_port_range,
    normalize_worker_transfer_ports,
)
from floability.workers_manager import _normalize_compute_specs


@pytest.mark.parametrize("value", ["9123:9150", "9123,9150", " 9123 : 9150 "])
def test_manager_ports_accept_both_forms_and_normalize_to_commas(value):
    assert normalize_manager_ports(value) == "9123,9150"


@pytest.mark.parametrize("value", ["10000:11000", "10000,11000"])
def test_worker_transfer_ports_accept_both_forms_and_normalize_to_colon(value):
    assert normalize_worker_transfer_ports(value) == "10000:11000"


@pytest.mark.parametrize(
    "value",
    ["9123", "9123:9150:9200", "abc:9150", "0:9150", "9150:9123"],
)
def test_invalid_port_ranges_are_rejected(value):
    with pytest.raises(ValueError):
        normalize_port_range(value)


def test_execution_parser_normalizes_both_port_options():
    parser = argparse.ArgumentParser()
    add_execution_args(parser)

    args = parser.parse_args(
        [
            "--manager-ports",
            "9123:9150",
            "--worker-transfer-ports",
            "10000,11000",
        ]
    )

    assert args.manager_ports == "9123,9150"
    assert args.worker_transfer_ports == "10000:11000"


def test_worker_configuration_normalizes_legacy_transfer_range():
    args = argparse.Namespace(worker_transfer_ports="10000,11000")

    config = _normalize_compute_specs(args, {})

    assert config["transfer_port"] == "10000:11000"
