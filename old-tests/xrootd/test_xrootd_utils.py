"""
Low-level unit tests for xrootd_file_utils.py.

Covers: parse_xrootd_uri, xrootd_file_metadata, is_xrootd_directory,
        xrootd_list_objects, xrootd_source_metadata.

Tests skip gracefully if the XRootD server is unreachable.
"""

import pytest
from pathlib import Path
import tempfile, shutil

from floability.data.xrootd_file_utils import (
    parse_xrootd_uri,
    xrootd_file_metadata,
    is_xrootd_directory,
    xrootd_list_objects,
    xrootd_source_metadata,
    xrootd_file_download,
)

# ── Test constants ────────────────────────────────────────────────────────────

SERVER       = "cmsxrootd.crc.nd.edu"
BASE         = f"root://{SERVER}"
FILE_URI     = f"{BASE}//store/user/jkil/2018/WJetsToLNu_HT-1200To2500_TuneCP5_13TeV-madgraphMLM-pythia8/WJetsHT1200To2500/260502_023848/0000/tree_1.root"
DIR_URI      = f"{BASE}//store/user/jkil/2018/WJetsToLNu_HT-1200To2500_TuneCP5_13TeV-madgraphMLM-pythia8/WJetsHT1200To2500/260502_023848/0000/"
FILE_SIZE    = 465160187
FILE_MD5     = "md5:923c3f8c61141f15eb2d5777c5ae4b75"


# ── Connectivity fixture ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def xrootd_available():
    """Skip the entire module if the XRootD server is unreachable."""
    meta = xrootd_file_metadata(FILE_URI)
    if not meta.get("exists"):
        err = meta.get("raw", {}).get("error", "unknown error")
        pytest.skip(f"XRootD server unreachable ({SERVER}): {err}")
    return True


# ── URI parsing (no network) ──────────────────────────────────────────────────

class TestParseXrootdUri:
    def test_standard_double_slash(self):
        server, path = parse_xrootd_uri("root://server//store/user/file.root")
        assert server == "root://server"
        assert path == "/store/user/file.root"

    def test_port(self):
        server, path = parse_xrootd_uri("root://server:1094//data/file.root")
        assert server == "root://server:1094"
        assert path == "/data/file.root"

    def test_trailing_slash(self):
        _, path = parse_xrootd_uri("root://server//some/dir/")
        assert path.endswith("/")

    def test_invalid_scheme(self):
        with pytest.raises(ValueError):
            parse_xrootd_uri("s3://bucket/key")

    def test_missing_server(self):
        with pytest.raises(ValueError):
            parse_xrootd_uri("root://")


# ── Metadata ──────────────────────────────────────────────────────────────────

class TestXrootdFileMetadata:
    def test_existing_file(self, xrootd_available):
        meta = xrootd_file_metadata(FILE_URI)
        assert meta["exists"] is True
        assert meta["type"] == "file"
        assert meta["size"] == FILE_SIZE
        assert meta["mtime"] is not None
        assert meta["checksum"] == FILE_MD5

    def test_nonexistent_file(self, xrootd_available):
        meta = xrootd_file_metadata(f"{BASE}//store/user/does_not_exist_xyz.root")
        assert meta["exists"] is False

    def test_directory_type(self, xrootd_available):
        meta = xrootd_file_metadata(DIR_URI)
        assert meta["exists"] is True
        assert meta["type"] == "directory"
        assert meta["checksum"] is None   # checksums not queried for directories


# ── Directory detection ───────────────────────────────────────────────────────

class TestIsXrootdDirectory:
    def test_file_is_not_dir(self, xrootd_available):
        assert is_xrootd_directory(FILE_URI) is False

    def test_dir_with_trailing_slash(self, xrootd_available):
        assert is_xrootd_directory(DIR_URI) is True

    def test_dir_without_trailing_slash(self, xrootd_available):
        dir_no_slash = DIR_URI.rstrip("/")
        assert is_xrootd_directory(dir_no_slash) is True


# ── Directory listing ─────────────────────────────────────────────────────────

class TestXrootdListObjects:
    def test_list_returns_files(self, xrootd_available):
        objects = xrootd_list_objects(DIR_URI, recursive=True, fetch_checksums=False)
        assert len(objects) >= 2
        for obj in objects:
            assert obj["type"] == "file"
            assert obj["size"] is not None
            assert obj["rel_path"] != ""

    def test_list_with_checksums(self, xrootd_available):
        objects = xrootd_list_objects(DIR_URI, recursive=True, fetch_checksums=True)
        files_with_cksum = [o for o in objects if o.get("checksum")]
        assert len(files_with_cksum) > 0

    def test_list_contains_known_file(self, xrootd_available):
        objects = xrootd_list_objects(DIR_URI, recursive=True, fetch_checksums=False)
        names = [o["name"] for o in objects]
        assert "tree_1.root" in names


# ── Source metadata (for cache key) ──────────────────────────────────────────

class TestXrootdSourceMetadata:
    def test_file_metadata(self, xrootd_available):
        meta = xrootd_source_metadata(FILE_URI)
        assert meta["ok"] is True
        assert meta["object_type"] == "file"
        assert meta["size"] == FILE_SIZE
        assert meta["checksum"] == FILE_MD5
        assert meta["mtime"] is not None

    def test_directory_metadata(self, xrootd_available):
        meta = xrootd_source_metadata(DIR_URI)
        assert meta["ok"] is True
        assert meta["object_type"] == "directory"
        assert meta["file_count"] >= 2
        assert meta["total_size"] > 0
        files = meta["files"]
        assert all("rel_path" in f for f in files)
        assert all("size" in f for f in files)
        # Files should be sorted by rel_path
        paths = [f["rel_path"] for f in files]
        assert paths == sorted(paths)


# ── File download (marked slow — skipped by default) ─────────────────────────

@pytest.mark.slow
class TestXrootdFileDownload:
    def test_download_single_file(self, xrootd_available):
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = xrootd_file_download(
                FILE_URI,
                dest_dir=tmpdir,
                filename="tree_1.root",
                overwrite=True,
                show_progress=True,
            )
            assert dest.exists()
            assert dest.stat().st_size == FILE_SIZE
