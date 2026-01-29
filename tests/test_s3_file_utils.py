"""
Tests for S3 file operations (s3_file_utils.py).

These tests cover low-level S3 operations:
- Parsing S3 URIs
- Fetching file metadata
- Downloading files from S3
- Listing S3 objects

NOTE: Requires AWS credentials configured via environment variables,
~/.aws/credentials, or IAM roles.
"""

import pytest
from pathlib import Path
import tempfile
import shutil
from floability.data.s3_file_utils import (
    parse_s3_uri,
    s3_file_metadata,
    s3_file_download,
    s3_list_objects,
)


# S3 test constants - using public bucket file
TEST_S3_URI = "s3://floability/coffea-sample-data/small_data.root"
TEST_S3_BUCKET = "floability"
TEST_S3_KEY = "coffea-sample-data/small_data.root"
TEST_S3_FILENAME = "small_data.root"
TEST_S3_SIZE = 282631  # ~280KB


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_download_dir():
    """Temporary directory for S3 downloads."""
    tmpdir = tempfile.mkdtemp(prefix="s3_test_")
    yield Path(tmpdir)
    shutil.rmtree(tmpdir, ignore_errors=True)


# =============================================================================
# Test S3 URI Parsing
# =============================================================================


class TestS3UriParsing:
    """Test parsing of S3 URIs."""

    def test_parse_s3_uri_basic(self):
        """Parse basic s3:// URI."""
        bucket, key = parse_s3_uri(TEST_S3_URI)
        assert bucket == TEST_S3_BUCKET
        assert key == TEST_S3_KEY

    def test_parse_s3_uri_with_prefix(self):
        """Parse s3:// URI with directory prefix."""
        uri = "s3://my-bucket/path/to/file.txt"
        bucket, key = parse_s3_uri(uri)
        assert bucket == "my-bucket"
        assert key == "path/to/file.txt"

    def test_parse_s3_uri_directory(self):
        """Parse s3:// URI ending with slash (directory)."""
        uri = "s3://my-bucket/path/to/dir/"
        bucket, key = parse_s3_uri(uri)
        assert bucket == "my-bucket"
        assert key == "path/to/dir/"

    def test_parse_s3_uri_invalid_scheme(self):
        """Parse URI with invalid scheme raises ValueError."""
        with pytest.raises(ValueError, match="Invalid S3 URI"):
            parse_s3_uri("https://floability.s3.amazonaws.com/file.txt")

    def test_parse_s3_uri_no_key(self):
        """Parse s3:// URI with bucket only."""
        uri = "s3://my-bucket/"
        bucket, key = parse_s3_uri(uri)
        assert bucket == "my-bucket"
        assert key == ""


# =============================================================================
# Test S3 File Metadata
# =============================================================================


class TestS3FileMetadata:
    """Test fetching metadata from S3 objects."""

    def test_s3_metadata_fetch(self):
        """Fetch metadata from existing S3 object (public bucket)."""
        import os
        os.environ['AWS_NO_SIGN_REQUEST'] = 'true'
        metadata = s3_file_metadata(TEST_S3_URI)
        
        assert "exists" in metadata
        assert metadata["exists"] is True
        assert "name" in metadata
        assert metadata["name"] == TEST_S3_FILENAME
        assert "size" in metadata
        assert metadata["size"] > 0  # Size varies
        assert "etag" in metadata
        assert "last_modified" in metadata
        assert "type" in metadata

    def test_s3_metadata_structure(self):
        """Verify metadata dictionary structure."""
        import os
        os.environ['AWS_NO_SIGN_REQUEST'] = 'true'
        metadata = s3_file_metadata(TEST_S3_URI)
        
        required_keys = {"exists", "name", "size", "type", "etag", "last_modified", "raw"}
        assert required_keys.issubset(metadata.keys())
        
        # Check types
        assert isinstance(metadata["exists"], bool)
        assert isinstance(metadata["name"], str)
        assert isinstance(metadata["size"], int)
        assert isinstance(metadata["type"], str)
        assert isinstance(metadata["etag"], str)
        assert metadata["size"] > 0

    def test_s3_metadata_nonexistent(self):
        """Attempt to fetch metadata from non-existent S3 object."""
        import os
        os.environ['AWS_NO_SIGN_REQUEST'] = 'true'
        uri = "s3://floability/does-not-exist-12345.txt"
        
        metadata = s3_file_metadata(uri)
        assert metadata["exists"] is False
        assert metadata["size"] is None


# =============================================================================
# Test S3 File Download
# =============================================================================


class TestS3FileDownload:
    """Test downloading files from S3."""

    def test_s3_download_basic(self, temp_download_dir):
        """Download file from S3 to local directory (public bucket)."""
        import os
        os.environ['AWS_NO_SIGN_REQUEST'] = 'true'
        downloaded_file = s3_file_download(
            TEST_S3_URI,
            dest_dir=str(temp_download_dir),
        )
        
        assert downloaded_file is not None
        file_path = Path(downloaded_file)
        assert file_path.exists()
        assert file_path.stat().st_size == TEST_S3_SIZE
        assert file_path.name == TEST_S3_FILENAME

    def test_s3_download_custom_filename(self, temp_download_dir):
        """Download S3 file with custom local filename."""
        import os
        os.environ['AWS_NO_SIGN_REQUEST'] = 'true'
        custom_name = "custom_file.root"
        downloaded_file = s3_file_download(
            TEST_S3_URI,
            dest_dir=str(temp_download_dir),
            filename=custom_name,
        )
        
        assert downloaded_file is not None
        file_path = Path(downloaded_file)
        assert file_path.exists()
        assert file_path.name == custom_name
        assert file_path.stat().st_size == TEST_S3_SIZE

    def test_s3_download_no_overwrite(self, temp_download_dir):
        """Download S3 file fails when target exists and overwrite=False, resume=False."""
        import os
        os.environ['AWS_NO_SIGN_REQUEST'] = 'true'
        # First download
        downloaded_file = s3_file_download(
            TEST_S3_URI,
            dest_dir=str(temp_download_dir),
        )
        assert Path(downloaded_file).exists()
        
        # Second download with overwrite=False and resume=False should raise
        with pytest.raises(FileExistsError):
            s3_file_download(
                TEST_S3_URI,
                dest_dir=str(temp_download_dir),
                overwrite=False,
                resume=False,
            )

    def test_s3_download_overwrite(self, temp_download_dir):
        """Download S3 file succeeds with overwrite=True."""
        import os
        os.environ['AWS_NO_SIGN_REQUEST'] = 'true'
        # First download
        downloaded_file = s3_file_download(
            TEST_S3_URI,
            dest_dir=str(temp_download_dir),
        )
        first_mtime = Path(downloaded_file).stat().st_mtime
        
        # Second download with overwrite=True should succeed
        downloaded_file_2 = s3_file_download(
            TEST_S3_URI,
            dest_dir=str(temp_download_dir),
            overwrite=True,
        )
        
        assert Path(downloaded_file_2).exists()
        assert downloaded_file == downloaded_file_2

    def test_s3_download_nonexistent(self, temp_download_dir):
        """Download non-existent S3 file raises error."""
        import os
        os.environ['AWS_NO_SIGN_REQUEST'] = 'true'
        uri = "s3://floability/does-not-exist-12345.txt"
        
        with pytest.raises(Exception):  # Will raise NoSuchKey error
            s3_file_download(uri, dest_dir=str(temp_download_dir))


# =============================================================================
# Test S3 List Objects
# =============================================================================


class TestS3ListObjects:
    """Test listing S3 bucket objects."""

    def test_s3_list_bucket_root(self):
        """List all objects in S3 bucket root."""
        import os
        os.environ['AWS_NO_SIGN_REQUEST'] = 'true'
        uri = "s3://floability/"
        objects = s3_list_objects(uri)
        
        assert isinstance(objects, list)
        assert len(objects) > 0
        
        # Check that test file is in the list
        keys = [obj["key"] for obj in objects]
        assert TEST_S3_KEY in keys

    def test_s3_list_prefix(self):
        """List objects with specific prefix."""
        import os
        os.environ['AWS_NO_SIGN_REQUEST'] = 'true'
        uri = "s3://floability/coffea-sample-data"
        objects = s3_list_objects(uri)
        
        assert isinstance(objects, list)
        # All returned keys should start with the prefix
        for obj in objects:
            assert obj["key"].startswith("coffea-sample-data")

    def test_s3_list_object_structure(self):
        """Verify structure of listed S3 objects."""
        import os
        os.environ['AWS_NO_SIGN_REQUEST'] = 'true'
        uri = "s3://floability/coffea-sample-data/"
        objects = s3_list_objects(uri, recursive=False)
        
        if len(objects) > 0:
            obj = objects[0]
            assert "key" in obj
            assert "size" in obj
            assert "last_modified" in obj
            assert "etag" in obj


# =============================================================================
# Test S3 Integration
# =============================================================================


class TestS3Integration:
    """Integration tests for S3 operations."""

    def test_metadata_then_download(self, temp_download_dir):
        """Fetch metadata, then download file and verify size matches."""
        import os
        os.environ['AWS_NO_SIGN_REQUEST'] = 'true'
        
        # Get metadata
        metadata = s3_file_metadata(TEST_S3_URI)
        expected_size = metadata["size"]
        
        # Download file and verify
        downloaded_file = s3_file_download(TEST_S3_URI, dest_dir=str(temp_download_dir))
        assert Path(downloaded_file).stat().st_size == expected_size
        assert expected_size == TEST_S3_SIZE

    def test_parse_download_uri(self):
        """Parse URI then use components for download."""
        bucket, key = parse_s3_uri(TEST_S3_URI)
        
        # Verify we can reconstruct the URI
        reconstructed = f"s3://{bucket}/{key}"
        assert reconstructed == TEST_S3_URI


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
