"""
Integration tests for XRootD support through data_handler.py.

Drives check / fetch / verify operations via the data.yml spec in this
directory, covering single-file, directory, and cache modes.

Tests marked @pytest.mark.slow download real data and are skipped by default.
Run with: pytest -m slow tests/xrootd/
"""

import pytest
import shutil
import tempfile
from pathlib import Path

from floability.data.data_handler import (
    check_data_from_spec,
    fetch_data_from_spec,
    verify_data_from_spec,
)
from floability.data.xrootd_file_utils import xrootd_file_metadata

# ── Paths ─────────────────────────────────────────────────────────────────────

DATA_SPEC   = Path(__file__).parent / "data.yml"
FILE_URI    = (
    "root://cmsxrootd.crc.nd.edu"
    "//store/user/jkil/2018"
    "/WJetsToLNu_HT-1200To2500_TuneCP5_13TeV-madgraphMLM-pythia8"
    "/WJetsHT1200To2500/260502_023848/0000/tree_1.root"
)


# ── Connectivity fixture ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def xrootd_available():
    meta = xrootd_file_metadata(FILE_URI)
    if not meta.get("exists"):
        err = meta.get("raw", {}).get("error", "unknown")
        pytest.skip(f"XRootD server unreachable: {err}")
    return True


@pytest.fixture
def workdir():
    """Temporary directory that acts as both backpack_root and base_dir."""
    d = tempfile.mkdtemp(prefix="xrootd_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


# ── check_data_from_spec ──────────────────────────────────────────────────────

class TestCheckXrootd:
    def test_check_single_file(self, xrootd_available, workdir):
        ok = check_data_from_spec(
            data_spec=str(DATA_SPEC),
            backpack_root=workdir,
            data_profile="single_file",
            verbose=True,
        )
        assert ok is True

    def test_check_directory(self, xrootd_available, workdir):
        ok = check_data_from_spec(
            data_spec=str(DATA_SPEC),
            backpack_root=workdir,
            data_profile="directory",
            verbose=True,
        )
        assert ok is True

    def test_check_with_cache_status(self, xrootd_available, workdir):
        """check reports cache status when cache mode is enabled (cache will be cold)."""
        ok = check_data_from_spec(
            data_spec=str(DATA_SPEC),
            backpack_root=workdir,
            data_profile="single_file",
            data_cache_mode="symlink",
            base_dir=workdir,
            verbose=True,
        )
        assert ok is True   # check does not require cache to be warm


# ── fetch_data_from_spec ──────────────────────────────────────────────────────

@pytest.mark.slow
class TestFetchXrootd:
    def test_fetch_single_file_no_cache(self, xrootd_available, workdir):
        target_root = workdir / "workflow"
        ok = fetch_data_from_spec(
            data_spec=str(DATA_SPEC),
            backpack_root=workdir,
            data_profile="single_file",
            data_cache_mode="off",
            target_root=target_root,
            verbose=True,
        )
        assert ok is True
        dest = target_root / "data" / "tree_1.root"
        assert dest.exists()
        assert dest.stat().st_size == 465160187

    def test_fetch_single_file_symlink_cache(self, xrootd_available, workdir):
        target_root = workdir / "workflow"
        ok = fetch_data_from_spec(
            data_spec=str(DATA_SPEC),
            backpack_root=workdir,
            data_profile="single_file",
            data_cache_mode="symlink",
            base_dir=workdir,
            target_root=target_root,
            verbose=True,
        )
        assert ok is True
        dest = target_root / "data" / "tree_1.root"
        assert dest.exists()
        assert dest.is_symlink()

    def test_fetch_second_call_uses_cache(self, xrootd_available, workdir):
        """Second fetch with cache enabled should reuse the cached entry."""
        target_root = workdir / "workflow"

        fetch_data_from_spec(
            data_spec=str(DATA_SPEC),
            backpack_root=workdir,
            data_profile="single_file",
            data_cache_mode="symlink",
            base_dir=workdir,
            target_root=target_root,
            verbose=True,
        )

        dest = target_root / "data" / "tree_1.root"
        first_resolved = dest.resolve()

        # Remove target but keep cache
        shutil.rmtree(target_root)
        target_root.mkdir(parents=True)

        fetch_data_from_spec(
            data_spec=str(DATA_SPEC),
            backpack_root=workdir,
            data_profile="single_file",
            data_cache_mode="symlink",
            base_dir=workdir,
            target_root=target_root,
            verbose=True,
        )

        dest2 = target_root / "data" / "tree_1.root"
        assert dest2.resolve() == first_resolved, "Second fetch should hit the same cache entry"

    def test_fetch_directory(self, xrootd_available, workdir):
        target_root = workdir / "workflow"
        ok = fetch_data_from_spec(
            data_spec=str(DATA_SPEC),
            backpack_root=workdir,
            data_profile="directory",
            data_cache_mode="off",
            target_root=target_root,
            verbose=True,
        )
        assert ok is True
        dest_dir = target_root / "data" / "wjets"
        assert dest_dir.is_dir()
        files = list(dest_dir.rglob("*.root"))
        assert len(files) >= 2


# ── verify_data_from_spec ─────────────────────────────────────────────────────

@pytest.mark.slow
class TestVerifyXrootd:
    def test_verify_single_file_strict(self, xrootd_available, workdir):
        """Verify with strict mode — checksum must match."""
        target_root = workdir / "workflow"
        ok = verify_data_from_spec(
            data_spec=str(DATA_SPEC),
            backpack_root=workdir,
            data_profile="single_file",
            data_cache_mode="off",
            target_root=target_root,
            verbose=True,
        )
        assert ok is True

    def test_verify_detects_corruption(self, xrootd_available, workdir):
        """Truncating the file should cause verify to fail the size check."""
        target_root = workdir / "workflow"

        fetch_data_from_spec(
            data_spec=str(DATA_SPEC),
            backpack_root=workdir,
            data_profile="single_file",
            data_cache_mode="off",
            target_root=target_root,
            verbose=False,
        )

        # Corrupt the file
        dest = target_root / "data" / "tree_1.root"
        dest.write_bytes(b"corrupted")

        ok = verify_data_from_spec(
            data_spec=str(DATA_SPEC),
            backpack_root=workdir,
            data_profile="single_file",
            data_cache_mode="off",
            target_root=target_root,
            verbose=False,
        )
        assert ok is False


# ── URI auto-detection ────────────────────────────────────────────────────────

class TestXrootdUriDetection:
    """Verify root:// URIs are auto-detected without explicit source_type."""

    def test_inline_spec_check(self, xrootd_available, workdir):
        import yaml, io
        spec = {
            "default_profile": "test",
            "data_profiles": {
                "test": {
                    "data": [{
                        "name": "inline_test",
                        "source": FILE_URI,          # no source_type — must be inferred
                        "target_location": "data/tree_1.root",
                    }]
                }
            }
        }
        spec_path = workdir / "inline_spec.yml"
        spec_path.write_text(yaml.safe_dump(spec))

        ok = check_data_from_spec(
            data_spec=str(spec_path),
            backpack_root=workdir,
            verbose=True,
        )
        assert ok is True
