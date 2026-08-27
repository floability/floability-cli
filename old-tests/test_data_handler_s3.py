"""
Tests for data handler with S3 sources (data_handler.py with S3).

These tests cover high-level data operations with S3 sources:
- check_data_from_spec() with S3
- fetch_data_from_spec() with S3 and various cache modes
- verify_data_from_spec() with S3

NOTE: Uses anonymous access for public floability S3 bucket.
"""

import pytest
from pathlib import Path
import tempfile
import shutil
import yaml
import os
from floability.data.data_handler import (
    check_data_from_spec,
    fetch_data_from_spec,
    verify_data_from_spec,
)


# S3 test constants - using public bucket file
TEST_S3_URI = "s3://floability/coffea-sample-data/small_data.root"
TEST_S3_FILENAME = "small_data.root"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def enable_anonymous_s3():
    """Enable anonymous S3 access for all tests in this module."""
    os.environ['AWS_NO_SIGN_REQUEST'] = 'true'
    yield
    # Clean up
    if 'AWS_NO_SIGN_REQUEST' in os.environ:
        del os.environ['AWS_NO_SIGN_REQUEST']


@pytest.fixture
def temp_backpack_dir():
    """Temporary backpack directory for tests."""
    tmpdir = tempfile.mkdtemp(prefix="s3_backpack_test_")
    yield Path(tmpdir)
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def test_s3_data_spec_path():
    """Path to S3 test data spec fixture."""
    return Path(__file__).parent / "fixtures" / "data" / "s3_single_item.yml"


# =============================================================================
# Test check_data_from_spec with S3
# =============================================================================


class TestCheckDataFromSpecS3:
    """Test checking data availability from S3 without downloading."""

    def test_check_s3_existing_file(self, test_s3_data_spec_path, temp_backpack_dir):
        """Check that existing S3 file is accessible (public bucket)."""
        result = check_data_from_spec(
            data_spec=str(test_s3_data_spec_path),
            backpack_root=temp_backpack_dir,
            verbose=True,
            data_cache_mode="off",
        )
        
        assert result is True, "Check should succeed for existing S3 file"

    def test_check_s3_nonexistent_file(self, temp_backpack_dir):
        """Check that non-existent S3 file is reported as unavailable."""
        spec_path = Path(__file__).parent / "fixtures" / "data" / "s3_nonexistent.yml"
        
        result = check_data_from_spec(
            data_spec=str(spec_path),
            backpack_root=temp_backpack_dir,
            verbose=True,
            data_cache_mode="off",
        )
        
        assert result is False, "Check should fail for non-existent S3 file"


# =============================================================================
# Test fetch_data_from_spec with S3
# =============================================================================


class TestFetchDataFromSpecS3:
    """Test fetching data from S3 with various cache modes."""

    def test_fetch_s3_cache_off(self, test_s3_data_spec_path, temp_backpack_dir):
        """Fetch S3 file with cache disabled (direct download)."""
        target_root = temp_backpack_dir / "workflow"
        target_root.mkdir(parents=True, exist_ok=True)
        
        result = fetch_data_from_spec(
            data_spec=str(test_s3_data_spec_path),
            backpack_root=temp_backpack_dir,
            data_cache_mode="off",
            target_root=target_root,
            verbose=True,
        )
        
        assert result is True, "Fetch should succeed"
        
        # Check that file was downloaded to target
        expected_file = target_root / "data" / TEST_S3_FILENAME
        assert expected_file.exists(), f"Expected file not found: {expected_file}"
        assert expected_file.stat().st_size > 0, "Downloaded file is empty"

    def test_fetch_s3_cache_symlink(self, test_s3_data_spec_path, temp_backpack_dir):
        """Fetch S3 file using symlink cache mode."""
        target_root = temp_backpack_dir / "workflow"
        target_root.mkdir(parents=True, exist_ok=True)
        
        result = fetch_data_from_spec(
            data_spec=str(test_s3_data_spec_path),
            backpack_root=temp_backpack_dir,
            data_cache_mode="symlink",
            target_root=target_root,
            base_dir=temp_backpack_dir,
            verbose=True,
        )
        
        assert result is True, "Fetch should succeed"
        
        # Check that file exists and is a symlink
        expected_file = target_root / "data" / TEST_S3_FILENAME
        assert expected_file.exists(), f"Expected file not found: {expected_file}"
        assert expected_file.is_symlink(), "File should be a symlink"

    def test_fetch_s3_cache_copy(self, test_s3_data_spec_path, temp_backpack_dir):
        """Fetch S3 file using copy cache mode."""
        target_root = temp_backpack_dir / "workflow"
        target_root.mkdir(parents=True, exist_ok=True)
        
        result = fetch_data_from_spec(
            data_spec=str(test_s3_data_spec_path),
            backpack_root=temp_backpack_dir,
            data_cache_mode="copy",
            target_root=target_root,
            base_dir=temp_backpack_dir,
            verbose=True,
        )
        
        assert result is True, "Fetch should succeed"
        
        # Check that file exists and is not a symlink (regular copy)
        expected_file = target_root / "data" / TEST_S3_FILENAME
        assert expected_file.exists(), f"Expected file not found: {expected_file}"
        assert not expected_file.is_symlink(), "File should be a regular copy, not a symlink"

    def test_fetch_s3_multiple_fetches(self, test_s3_data_spec_path, temp_backpack_dir):
        """Fetch same S3 file twice to verify cache reuse."""
        target_root = temp_backpack_dir / "workflow"
        target_root.mkdir(parents=True, exist_ok=True)
        
        # First fetch
        result1 = fetch_data_from_spec(
            data_spec=str(test_s3_data_spec_path),
            backpack_root=temp_backpack_dir,
            data_cache_mode="symlink",
            target_root=target_root,
            base_dir=temp_backpack_dir,
            verbose=True,
        )
        
        assert result1 is True, "First fetch should succeed"
        
        # Clean target directory but keep cache
        expected_file = target_root / "data" / TEST_S3_FILENAME
        first_cache_target = expected_file.resolve()
        shutil.rmtree(target_root)
        target_root.mkdir(parents=True, exist_ok=True)
        
        # Second fetch (should use cache)
        result2 = fetch_data_from_spec(
            data_spec=str(test_s3_data_spec_path),
            backpack_root=temp_backpack_dir,
            data_cache_mode="symlink",
            target_root=target_root,
            base_dir=temp_backpack_dir,
            verbose=True,
        )
        
        assert result2 is True, "Second fetch should succeed"
        
        # Verify both fetches used same cache file
        expected_file = target_root / "data" / TEST_S3_FILENAME
        second_cache_target = expected_file.resolve()
        assert first_cache_target == second_cache_target, "Both fetches should use same cache file"


# =============================================================================
# Test verify_data_from_spec with S3
# =============================================================================


class TestVerifyDataFromSpecS3:
    """Test verifying data integrity from S3."""

    def test_verify_s3_file(self, test_s3_data_spec_path, temp_backpack_dir):
        """Verify S3 file after download."""
        target_root = temp_backpack_dir / "workflow"
        target_root.mkdir(parents=True, exist_ok=True)
        
        result = verify_data_from_spec(
            data_spec=str(test_s3_data_spec_path),
            backpack_root=temp_backpack_dir,
            data_cache_mode="off",
            target_root=target_root,
            verbose=True,
        )
        
        assert result is True, "Verify should succeed"
        
        # Check that file was downloaded
        expected_file = target_root / "data" / TEST_S3_FILENAME
        assert expected_file.exists(), f"Expected file not found: {expected_file}"


# =============================================================================
# Test S3 URI Detection
# =============================================================================


class TestS3UriDetection:
    """Test automatic detection of S3 URIs in data specs."""

    def test_s3_uri_check(self, temp_backpack_dir):
        """Verify s3:// URIs work in check operation."""
        spec_data = {
            "default_profile": "test",
            "profiles": {
                "test": {
                    "data": [
                        {
                            "name": "test-s3-file",
                            "source": TEST_S3_URI,
                            "target_path": "data/test.root",
                        }
                    ]
                }
            }
        }
        
        spec_path = temp_backpack_dir / "test_spec.yml"
        with open(spec_path, "w") as f:
            yaml.dump(spec_data, f)
        
        result = check_data_from_spec(
            data_spec=str(spec_path),
            backpack_root=temp_backpack_dir,
            verbose=True,
            data_cache_mode="off",
        )
        
        assert result is True, "S3 URI should be detected and checked successfully"

    def test_s3_https_uri_requires_explicit_type(self, temp_backpack_dir):
        """Verify https:// S3 URLs require explicit source_type."""
        spec_data = {
            "default_profile": "test",
            "profiles": {
                "test": {
                    "data": [
                        {
                            "name": "test-http-s3",
                            "source": "https://floability.s3.us-east-1.amazonaws.com/coffea-sample-data/small_data.root",
                            "source_type": "http",  # Must be explicit
                            "target_path": "data/test.root",
                        }
                    ]
                }
            }
        }
        
        spec_path = temp_backpack_dir / "test_spec.yml"
        with open(spec_path, "w") as f:
            yaml.dump(spec_data, f)
        
        result = check_data_from_spec(
            data_spec=str(spec_path),
            backpack_root=temp_backpack_dir,
            verbose=True,
            data_cache_mode="off",
        )
        
        # Should work via HTTP
        assert result is True, "HTTPS S3 URL should work with explicit http source_type"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
