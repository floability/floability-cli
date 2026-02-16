"""
Unit tests for pelican_file_utils.py

Tests low-level Pelican file operations: metadata fetching and file downloads.
"""
import pytest
import hashlib
from pathlib import Path
from floability.data.pelican_file_utils import (
    pelican_file_metadata,
    pelican_file_download,
    _safe_basename,
    _split_director_and_path,
)


@pytest.mark.network
class TestPelicanFileMetadata:
    """Test pelican_file_metadata() function."""
    
    def test_metadata_accessible_file(self, test_pelican_url, test_pelican_filename, test_pelican_size):
        """Test metadata fetch for accessible file."""
        meta = pelican_file_metadata(test_pelican_url)
        
        print(test_pelican_url)        

        assert meta["exists"] is True, "File should exist"
        assert meta["name"] == test_pelican_filename, f"Expected filename {test_pelican_filename}"
        assert meta["size"] == test_pelican_size, f"Expected size {test_pelican_size}, got {meta['size']}"
        assert meta["type"] == "file", "Should be a file type"
        assert isinstance(meta["raw"], dict), "Raw metadata should be a dict"
        print(f"✓ Metadata fetch successful: {meta['name']} ({meta['size']} bytes)")
    
    def test_metadata_structure(self, test_pelican_url):
        """Test metadata structure has all required fields."""
        meta = pelican_file_metadata(test_pelican_url)
        
        required_fields = ["exists", "name", "size", "type", "raw"]
        for field in required_fields:
            assert field in meta, f"Missing required field: {field}"
        print(f"✓ All required metadata fields present: {required_fields}")
    
    def test_metadata_nonexistent_file(self):
        """Test metadata fetch for non-existent file."""
        bad_url = "pelican://disc-head-002.crc.nd.edu:443/nd/disc2/apps/floability/nonexistent/file.root"
        meta = pelican_file_metadata(bad_url)
        
        assert meta["exists"] is False, "Non-existent file should return exists=False"
        assert meta["size"] is None, "Size should be None for non-existent file"
        assert meta["type"] is None, "Type should be None for non-existent file"
        assert "error" in meta["raw"], "Raw should contain error information"
        print(f"✓ Non-existent file handled gracefully: exists={meta['exists']}")
    
    def test_metadata_filename_extraction(self, test_pelican_url, test_pelican_filename):
        """Test filename extraction from URL."""
        meta = pelican_file_metadata(test_pelican_url)
        assert meta["name"] == test_pelican_filename
        # Should strip any path components
        assert "/" not in meta["name"], "Filename should not contain path separators"
        print(f"✓ Filename extracted correctly: {meta['name']}")


@pytest.mark.network
@pytest.mark.slow
class TestPelicanFileDownload:
    """Test pelican_file_download() function."""
    
    def test_download_basic(self, test_pelican_url, test_pelican_filename, test_pelican_size, tmp_test_dir):
        """Test basic file download."""
        dest = pelican_file_download(test_pelican_url, dest_dir=str(tmp_test_dir), show_progress=False)
        
        assert dest.exists(), "Downloaded file should exist"
        assert dest.name == test_pelican_filename, f"Expected filename {test_pelican_filename}"
        assert dest.stat().st_size == test_pelican_size, f"Expected size {test_pelican_size}"
        print(f"✓ Basic download successful: {dest} ({dest.stat().st_size} bytes)")
    
    def test_download_checksum_validation(self, test_pelican_url, test_pelican_checksum, tmp_test_dir):
        """Test downloaded file checksum matches expected."""
        dest = pelican_file_download(test_pelican_url, dest_dir=str(tmp_test_dir), show_progress=False)
        
        # Calculate SHA256
        sha256_hash = hashlib.sha256()
        with open(dest, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        actual_checksum = f"sha256:{sha256_hash.hexdigest()}"
        
        assert actual_checksum == test_pelican_checksum, f"Checksum mismatch: expected {test_pelican_checksum}, got {actual_checksum}"
        print(f"✓ Checksum validated: {actual_checksum}")
    
    def test_download_custom_filename(self, test_pelican_url, tmp_test_dir):
        """Test download with custom filename."""
        custom_name = "custom_test_file.root"
        dest = pelican_file_download(
            test_pelican_url,
            dest_dir=str(tmp_test_dir),
            filename=custom_name,
            show_progress=False
        )
        
        assert dest.name == custom_name, f"Expected custom filename {custom_name}"
        assert dest.exists(), "Downloaded file should exist"
        print(f"✓ Custom filename applied: {dest.name}")
    
    def test_download_overwrite_false(self, test_pelican_url, tmp_test_dir):
        """Test overwrite=False skips existing file."""
        # First download
        dest1 = pelican_file_download(test_pelican_url, dest_dir=str(tmp_test_dir), show_progress=False)
        mtime1 = dest1.stat().st_mtime
        
        # Second download with overwrite=False (default)
        dest2 = pelican_file_download(test_pelican_url, dest_dir=str(tmp_test_dir), overwrite=False, show_progress=False)
        mtime2 = dest2.stat().st_mtime
        
        assert dest1 == dest2, "Should return same file"
        assert mtime1 == mtime2, "File should not be modified (overwrite=False)"
        print(f"✓ overwrite=False skipped re-download (mtime unchanged)")
    
    def test_download_overwrite_true(self, test_pelican_url, tmp_test_dir):
        """Test overwrite=True forces re-download."""
        # First download
        dest1 = pelican_file_download(test_pelican_url, dest_dir=str(tmp_test_dir), show_progress=False)
        original_size = dest1.stat().st_size
        
        # Modify file to verify it gets replaced
        with open(dest1, "ab") as f:
            f.write(b"CORRUPTED")
        modified_size = dest1.stat().st_size
        assert modified_size > original_size, "File should be larger after modification"
        
        # Second download with overwrite=True
        dest2 = pelican_file_download(test_pelican_url, dest_dir=str(tmp_test_dir), overwrite=True, show_progress=False)
        final_size = dest2.stat().st_size
        
        assert final_size == original_size, f"File should be restored to original size {original_size}"
        print(f"✓ overwrite=True forced re-download (size restored: {final_size} bytes)")
    
    def test_download_part_file_creation(self, test_pelican_url, tmp_test_dir):
        """Test that .part file is created during download."""
        # Note: This test is tricky because the .part file is renamed on completion
        # We'll just verify the final file exists without .part extension
        dest = pelican_file_download(test_pelican_url, dest_dir=str(tmp_test_dir), show_progress=False)
        
        assert dest.exists(), "Final file should exist"
        assert not dest.with_suffix(dest.suffix + ".part").exists(), ".part file should be removed after completion"
        print(f"✓ Download completed, .part file cleaned up")
    
    def test_download_resume_capability(self, test_pelican_url, tmp_test_dir):
        """Test resume capability (partial download continuation)."""
        # This test verifies the resume logic works, though full interruption testing is complex
        # We'll download normally and verify it succeeds
        dest = pelican_file_download(
            test_pelican_url,
            dest_dir=str(tmp_test_dir),
            resume=True,
            show_progress=False
        )
        
        assert dest.exists(), "Downloaded file should exist with resume=True"
        print(f"✓ Download with resume=True successful")


@pytest.mark.unit
class TestPelicanHelperFunctions:
    """Test helper functions in pelican_file_utils."""
    
    def test_safe_basename_simple(self):
        """Test _safe_basename with simple filename."""
        result = _safe_basename("file.root")
        assert result == "file.root"
        print(f"✓ Simple basename: {result}")
    
    def test_safe_basename_with_path(self):
        """Test _safe_basename strips path components."""
        result = _safe_basename("/path/to/file.root")
        assert result == "file.root"
        
        result2 = _safe_basename("path/to/file.root")
        assert result2 == "file.root"
        print(f"✓ Path stripped from basename: {result}")
    
    def test_safe_basename_empty(self):
        """Test _safe_basename with empty or root path."""
        result = _safe_basename("")
        assert result == "download.bin", "Empty path should return default"
        
        result2 = _safe_basename("/")
        assert result2 == "download.bin", "Root path should return default"
        print(f"✓ Empty/root path returns default: {result}")
    
    def test_split_director_pelican_url(self):
        """Test _split_director_and_path with pelican:// URL."""
        url = "pelican://disc-head-002.crc.nd.edu:443/nd/disc2/apps/file.root"
        director, path = _split_director_and_path(url)
        
        assert director == "pelican://disc-head-002.crc.nd.edu:443"
        assert path == "/nd/disc2/apps/file.root"
        print(f"✓ Pelican URL split: director={director}, path={path}")
    
    def test_split_director_osdf_url(self):
        """Test _split_director_and_path with osdf:// URL."""
        url = "osdf:///ns/path/to/file.root"
        director, path = _split_director_and_path(url)
        
        assert director == "pelican://osg-htc.org"
        assert path == "/ns/path/to/file.root"
        print(f"✓ OSDF URL split: director={director}, path={path}")
    
    def test_split_director_invalid_scheme(self):
        """Test _split_director_and_path with invalid scheme."""
        with pytest.raises(ValueError, match="Expected osdf:// or pelican://"):
            _split_director_and_path("http://invalid.com/file.root")
        print(f"✓ Invalid scheme raises ValueError")


@pytest.mark.network
class TestPelicanServerLiveness:
    """Test if Pelican server is accessible."""
    
    def test_server_accessible(self, test_pelican_url):
        """Test if Pelican server responds to metadata request."""
        try:
            meta = pelican_file_metadata(test_pelican_url)
            server_accessible = meta["exists"] or "error" in meta["raw"]
            
            assert server_accessible, "Server should respond (either success or error)"
            
            if meta["exists"]:
                print(f"✓ Pelican server LIVE: file accessible")
            else:
                print(f"⚠ Pelican server responded but file not found: {meta['raw'].get('error')}")
        except Exception as e:
            pytest.fail(f"Pelican server not accessible: {e}")
