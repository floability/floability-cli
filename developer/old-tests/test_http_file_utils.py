"""
Unit tests for http_file_utils.py

Tests low-level HTTP file operations: metadata fetching and file downloads.
"""
import pytest
import hashlib
from pathlib import Path
from floability.data.http_file_utils import (
    http_file_metadata,
    http_file_download,
)


@pytest.mark.network
class TestHttpFileMetadata:
    """Test http_file_metadata() function."""
    
    def test_metadata_accessible_file(self, test_http_url, test_http_filename, test_http_size):
        """Test metadata fetch for accessible file."""
        meta = http_file_metadata(test_http_url)
        
        assert meta["exists"] is True, "File should exist"
        assert meta["name"] == test_http_filename, f"Expected filename {test_http_filename}"
        # HTTP metadata might not always return exact size, so we check if it's close
        if meta["size"]:
            assert abs(meta["size"] - test_http_size) < 1000, f"Size should be close to {test_http_size}"
        assert isinstance(meta["raw"], dict), "Raw metadata should be a dict"
        print(f"✓ Metadata fetch successful: {meta['name']} ({meta['size']} bytes)")
    
    def test_metadata_structure(self, test_http_url):
        """Test metadata structure has all required fields."""
        meta = http_file_metadata(test_http_url)
        
        required_fields = ["exists", "name", "size", "type", "raw"]
        for field in required_fields:
            assert field in meta, f"Missing required field: {field}"
        print(f"✓ All required metadata fields present: {required_fields}")
    
    def test_metadata_nonexistent_file(self):
        """Test metadata fetch for non-existent file."""
        bad_url = "https://www.gutenberg.org/nonexistent/file12345.txt"
        meta = http_file_metadata(bad_url)
        
        assert meta["exists"] is False, "Non-existent file should return exists=False"
        assert "error" in meta["raw"] or meta["raw"].get("status") == 404, "Should contain error information"
        print(f"✓ Non-existent file handled gracefully: exists={meta['exists']}")


@pytest.mark.network
@pytest.mark.slow
class TestHttpFileDownload:
    """Test http_file_download() function."""
    
    def test_download_basic(self, test_http_url, test_http_filename, tmp_test_dir):
        """Test basic file download."""
        dest = http_file_download(test_http_url, dest_dir=str(tmp_test_dir), show_progress=False)
        
        assert dest.exists(), "Downloaded file should exist"
        assert dest.name == test_http_filename, f"Expected filename {test_http_filename}"
        print(f"✓ Basic download successful: {dest} ({dest.stat().st_size} bytes)")
    
    def test_download_checksum_validation(self, test_http_url, test_http_checksum, tmp_test_dir):
        """Test downloaded file checksum matches expected."""
        dest = http_file_download(test_http_url, dest_dir=str(tmp_test_dir), show_progress=False)
        
        # Calculate SHA256
        sha256_hash = hashlib.sha256()
        with open(dest, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        actual_checksum = f"sha256:{sha256_hash.hexdigest()}"
        
        assert actual_checksum == test_http_checksum, f"Checksum mismatch: expected {test_http_checksum}, got {actual_checksum}"
        print(f"✓ Checksum validated: {actual_checksum}")
    
    def test_download_custom_filename(self, test_http_url, tmp_test_dir):
        """Test download with custom filename."""
        custom_name = "custom_gatsby.txt"
        dest = http_file_download(
            test_http_url,
            dest_dir=str(tmp_test_dir),
            filename=custom_name,
            show_progress=False
        )
        
        assert dest.name == custom_name, f"Expected custom filename {custom_name}"
        assert dest.exists(), "Downloaded file should exist"
        print(f"✓ Custom filename applied: {dest.name}")
    
    def test_download_overwrite_false(self, test_http_url, tmp_test_dir):
        """Test overwrite=False skips existing file."""
        # First download
        dest1 = http_file_download(test_http_url, dest_dir=str(tmp_test_dir), show_progress=False)
        mtime1 = dest1.stat().st_mtime
        
        # Second download with overwrite=False (default)
        dest2 = http_file_download(test_http_url, dest_dir=str(tmp_test_dir), overwrite=False, show_progress=False)
        mtime2 = dest2.stat().st_mtime
        
        assert dest1 == dest2, "Should return same file"
        assert mtime1 == mtime2, "File should not be modified (overwrite=False)"
        print(f"✓ overwrite=False skipped re-download (mtime unchanged)")
    
    def test_download_overwrite_true(self, test_http_url, tmp_test_dir):
        """Test overwrite=True forces re-download."""
        # First download
        dest1 = http_file_download(test_http_url, dest_dir=str(tmp_test_dir), show_progress=False)
        original_size = dest1.stat().st_size
        
        # Modify file to verify it gets replaced
        with open(dest1, "ab") as f:
            f.write(b"CORRUPTED")
        modified_size = dest1.stat().st_size
        assert modified_size > original_size, "File should be larger after modification"
        
        # Second download with overwrite=True
        dest2 = http_file_download(test_http_url, dest_dir=str(tmp_test_dir), overwrite=True, show_progress=False)
        final_size = dest2.stat().st_size
        
        assert final_size == original_size, f"File should be restored to original size {original_size}"
        print(f"✓ overwrite=True forced re-download (size restored: {final_size} bytes)")


@pytest.mark.network
class TestHttpServerAccess:
    """Test if HTTP server is accessible."""
    
    def test_server_accessible(self, test_http_url):
        """Test if HTTP server responds to metadata request."""
        try:
            meta = http_file_metadata(test_http_url)
            server_accessible = meta["exists"] or "error" in meta["raw"]
            
            assert server_accessible, "Server should respond (either success or error)"
            
            if meta["exists"]:
                print(f"✓ HTTP server LIVE: file accessible")
            else:
                print(f"⚠ HTTP server responded but file not found: {meta['raw'].get('error')}")
        except Exception as e:
            pytest.fail(f"HTTP server not accessible: {e}")
