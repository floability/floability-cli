"""
Functional tests for data_handler.py

Tests high-level data operations: check, fetch, verify with data specs.
"""
import pytest
import hashlib
import time
from pathlib import Path
from floability.data.data_handler import (
    check_data_from_spec,
    fetch_data_from_spec,
    verify_data_from_spec,
    execute_default_data_operation,
)


@pytest.mark.network
class TestCheckDataFromSpec:
    """Test check_data_from_spec() function."""
    
    def test_check_returns_true_accessible_file(self, test_data_spec_path, test_backpack_root):
        """Test check returns True for accessible file."""
        result = check_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off"
        )
        
        assert result is True, "Check should return True for accessible file"
        print(f"✓ check_data_from_spec returned True for accessible file")
    
    def test_check_metadata_only_no_download(self, test_data_spec_path, test_backpack_root, mock_base_dir):
        """Test check fetches metadata without downloading."""
        workflow_dir = mock_base_dir / "workflow"
        
        # Ensure workflow dir is empty before check
        assert not list(workflow_dir.glob("**/*.root")), "No .root files should exist before check"
        
        result = check_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off",
            base_dir=mock_base_dir
        )
        
        # Verify no files were downloaded
        assert not list(workflow_dir.glob("**/*.root")), "Check should not download files"
        assert result is True, "Check should succeed"
        print(f"✓ check_data_from_spec verified metadata without downloading")
    
    def test_check_size_tolerance(self, tmp_test_dir, test_backpack_root):
        """Test size tolerance logic in check."""
        # Create a test spec with strict size tolerance
        test_spec = tmp_test_dir / "test_size_tolerance.yml"
        test_spec.write_text("""
schema_version: 1.0
default_profile: strict_size

profiles:
  strict_size:
    policy:
      size_tolerance_bytes: 0
    data:
      - name: test_file
        source_type: pelican
        source: pelican://disc-head-002.crc.nd.edu:443/nd/disc2/apps/floability/examples/cms-physics-dv5/data/samples/diboson/zz/nano_mc2017_6.root
        expected_size: 190634
        target_path: data/test.root
""")
        
        result = check_data_from_spec(
            data_spec=str(test_spec),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off"
        )
        
        assert result is True, "Check should pass with exact size match"
        print(f"✓ Size tolerance check passed")
    
    def test_check_cache_mode_off(self, test_data_spec_path, test_backpack_root, mock_base_dir):
        """Test check with cache_mode='off'."""
        result = check_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off",
            base_dir=mock_base_dir
        )
        
        cache_dir = mock_base_dir / "flo_data_cache"
        # With cache_mode='off', cache should not be created during check
        # (check is metadata-only anyway)
        assert result is True
        print(f"✓ check with cache_mode='off' completed")
    
    def test_check_cache_mode_symlink(self, test_data_spec_path, test_backpack_root, mock_base_dir):
        """Test check with cache_mode='symlink'."""
        result = check_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="symlink",
            base_dir=mock_base_dir,
            show_details=True
        )
        
        assert result is True
        print(f"✓ check with cache_mode='symlink' completed")
    
    def test_check_nonexistent_file(self, test_backpack_root):
        """Test check returns False for non-existent file."""
        nonexistent_spec = Path(__file__).parent / "fixtures" / "data" / "pelican_nonexistent.yml"
        
        result = check_data_from_spec(
            data_spec=str(nonexistent_spec),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off"
        )
        
        assert result is False, "Check should return False for non-existent file"
        print(f"✓ check_data_from_spec correctly returned False for non-existent file")


@pytest.mark.network
@pytest.mark.slow
class TestFetchDataFromSpec:
    """Test fetch_data_from_spec() function."""
    
    def test_fetch_basic(self, test_data_spec_path, test_backpack_root, mock_base_dir):
        """Test basic fetch operation."""
        target_root = mock_base_dir / "workflow"
        
        result = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        
        assert result is True, "Fetch should succeed"
        
        # Verify file materialized
        expected_file = target_root / "data" / "samples" / "diboson" / "zz" / "nano_mc2017_6.root"
        assert expected_file.exists(), f"Expected file at {expected_file}"
        print(f"✓ File fetched successfully to {expected_file}")
    
    def test_fetch_file_integrity(self, test_data_spec_path, test_backpack_root, mock_base_dir, test_pelican_size, test_pelican_checksum):
        """Test fetched file has correct size and checksum."""
        target_root = mock_base_dir / "workflow"
        
        result = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        
        assert result is True
        
        target_file = target_root / "data" / "samples" / "diboson" / "zz" / "nano_mc2017_6.root"
        
        # Check size
        actual_size = target_file.stat().st_size
        assert actual_size == test_pelican_size, f"Size mismatch: expected {test_pelican_size}, got {actual_size}"
        
        # Check checksum
        sha256_hash = hashlib.sha256()
        with open(target_file, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        actual_checksum = f"sha256:{sha256_hash.hexdigest()}"
        
        assert actual_checksum == test_pelican_checksum, f"Checksum mismatch"
        print(f"✓ File integrity verified: size={actual_size}, checksum={actual_checksum}")
    
    def test_fetch_force_false_skip_existing(self, test_data_spec_path, test_backpack_root, mock_base_dir):
        """Test force=False skips existing file."""
        target_root = mock_base_dir / "workflow"
        
        # First fetch
        result1 = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            force=False,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        assert result1 is True
        
        target_file = target_root / "data" / "samples" / "diboson" / "zz" / "nano_mc2017_6.root"
        mtime1 = target_file.stat().st_mtime
        
        # Wait a moment
        time.sleep(0.1)
        
        # Second fetch with force=False
        result2 = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            force=False,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        assert result2 is True
        
        mtime2 = target_file.stat().st_mtime
        assert mtime1 == mtime2, "File should not be re-fetched with force=False"
        print(f"✓ force=False skipped existing file (mtime unchanged)")
    
    def test_fetch_force_true_redownload(self, test_data_spec_path, test_backpack_root, mock_base_dir):
        """Test force=True forces re-download."""
        target_root = mock_base_dir / "workflow"
        
        # First fetch
        result1 = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            force=False,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        assert result1 is True
        
        target_file = target_root / "data" / "samples" / "diboson" / "zz" / "nano_mc2017_6.root"
        original_size = target_file.stat().st_size
        
        # Corrupt file
        with open(target_file, "ab") as f:
            f.write(b"CORRUPTED")
        corrupted_size = target_file.stat().st_size
        assert corrupted_size > original_size
        
        # Second fetch with force=True
        result2 = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            force=True,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        assert result2 is True
        
        restored_size = target_file.stat().st_size
        assert restored_size == original_size, f"force=True should restore original file"
        print(f"✓ force=True forced re-download and restored file")
    
    def test_fetch_cache_mode_off(self, test_data_spec_path, test_backpack_root, mock_base_dir):
        """Test fetch with cache_mode='off' (direct download)."""
        target_root = mock_base_dir / "workflow"
        
        result = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        
        assert result is True
        
        # Verify file exists in target
        target_file = target_root / "data" / "samples" / "diboson" / "zz" / "nano_mc2017_6.root"
        assert target_file.exists()
        
        # Verify NO cache was created
        cache_dir = mock_base_dir / "flo_data_cache"
        cache_entries = list(cache_dir.glob("**/*.root"))
        assert len(cache_entries) == 0, "No cache should be created with cache_mode='off'"
        print(f"✓ fetch with cache_mode='off' bypassed cache")
    
    def test_fetch_cache_mode_symlink(self, test_data_spec_path, test_backpack_root, mock_base_dir, cleanup_cache):
        """Test fetch with cache_mode='symlink' (cache then symlink)."""
        target_root = mock_base_dir / "workflow"
        
        result = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="symlink",
            base_dir=mock_base_dir,
            target_root=target_root,
            fingerprint_mode="meta"
        )
        
        assert result is True
        
        target_file = target_root / "data" / "samples" / "diboson" / "zz" / "nano_mc2017_6.root"
        assert target_file.exists()
        
        # Verify it's a symlink
        assert target_file.is_symlink(), "Target should be a symlink with cache_mode='symlink'"
        
        # Verify cache exists
        cache_dir = mock_base_dir / "flo_data_cache"
        cache_entries = list(cache_dir.glob("**/*.root"))
        assert len(cache_entries) >= 1, "Cache entry should exist"
        
        # Verify symlink points to cache
        link_target = target_file.resolve()
        assert str(link_target).startswith(str(cache_dir)), "Symlink should point to cache"
        print(f"✓ fetch with cache_mode='symlink' created symlink to cache: {link_target}")
    
    def test_fetch_cache_mode_hardlink(self, test_data_spec_path, test_backpack_root, mock_base_dir, cleanup_cache):
        """Test fetch with cache_mode='hardlink'."""
        target_root = mock_base_dir / "workflow"
        
        result = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="hardlink",
            base_dir=mock_base_dir,
            target_root=target_root,
            fingerprint_mode="meta"
        )
        
        assert result is True
        
        target_file = target_root / "data" / "samples" / "diboson" / "zz" / "nano_mc2017_6.root"
        assert target_file.exists()
        
        # Verify it's NOT a symlink
        assert not target_file.is_symlink(), "Target should not be a symlink with cache_mode='hardlink'"
        
        # Verify cache exists
        cache_dir = mock_base_dir / "flo_data_cache"
        cache_entries = list(cache_dir.glob("**/*.root"))
        assert len(cache_entries) >= 1, "Cache entry should exist"
        
        # Verify shared inode (hardlink)
        cache_file = cache_entries[0]
        target_inode = target_file.stat().st_ino
        cache_inode = cache_file.stat().st_ino
        assert target_inode == cache_inode, "Target and cache should share inode (hardlink)"
        print(f"✓ fetch with cache_mode='hardlink' created hardlink (shared inode: {target_inode})")
    
    def test_fetch_cache_mode_copy(self, test_data_spec_path, test_backpack_root, mock_base_dir, cleanup_cache):
        """Test fetch with cache_mode='copy'."""
        target_root = mock_base_dir / "workflow"
        
        result = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="copy",
            base_dir=mock_base_dir,
            target_root=target_root,
            fingerprint_mode="meta"
        )
        
        assert result is True
        
        target_file = target_root / "data" / "samples" / "diboson" / "zz" / "nano_mc2017_6.root"
        assert target_file.exists()
        
        # Verify it's NOT a symlink
        assert not target_file.is_symlink(), "Target should not be a symlink with cache_mode='copy'"
        
        # Verify cache exists
        cache_dir = mock_base_dir / "flo_data_cache"
        cache_entries = list(cache_dir.glob("**/*.root"))
        assert len(cache_entries) >= 1, "Cache entry should exist"
        
        # Verify independent file (different inodes)
        cache_file = cache_entries[0]
        target_inode = target_file.stat().st_ino
        cache_inode = cache_file.stat().st_ino
        assert target_inode != cache_inode, "Target and cache should have different inodes (copy)"
        print(f"✓ fetch with cache_mode='copy' created independent copy (target inode: {target_inode}, cache inode: {cache_inode})")
    
    def test_fetch_cache_structure(self, test_data_spec_path, test_backpack_root, mock_base_dir, cleanup_cache):
        """Test cache directory structure is created correctly."""
        target_root = mock_base_dir / "workflow"
        
        result = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="symlink",
            base_dir=mock_base_dir,
            target_root=target_root,
            fingerprint_mode="meta"
        )
        
        assert result is True
        
        cache_dir = mock_base_dir / "flo_data_cache"
        assert cache_dir.exists(), "Cache directory should exist"
        assert cache_dir.is_dir(), "Cache should be a directory"
        
        # Check for cache structure (cache entries organized by hash)
        cache_entries = list(cache_dir.glob("**/*"))
        assert len(cache_entries) > 0, "Cache should contain entries"
        print(f"✓ Cache structure created: {len(cache_entries)} entries")
    
    def test_fetch_fingerprint_mode_meta(self, test_data_spec_path, test_backpack_root, mock_base_dir, cleanup_cache):
        """Test fetch with fingerprint_mode='meta'."""
        target_root = mock_base_dir / "workflow"
        
        result = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="symlink",
            base_dir=mock_base_dir,
            target_root=target_root,
            fingerprint_mode="meta"
        )
        
        assert result is True
        print(f"✓ fetch with fingerprint_mode='meta' successful")
    
    def test_fetch_fingerprint_mode_sample(self, test_data_spec_path, test_backpack_root, mock_base_dir, cleanup_cache):
        """Test fetch with fingerprint_mode='sample'."""
        target_root = mock_base_dir / "workflow"
        
        result = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="symlink",
            base_dir=mock_base_dir,
            target_root=target_root,
            fingerprint_mode="sample"
        )
        
        assert result is True
        print(f"✓ fetch with fingerprint_mode='sample' successful")
    
    def test_fetch_fingerprint_mode_strict(self, test_data_spec_path, test_backpack_root, mock_base_dir, cleanup_cache):
        """Test fetch with fingerprint_mode='strict'."""
        target_root = mock_base_dir / "workflow"
        
        result = fetch_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="symlink",
            base_dir=mock_base_dir,
            target_root=target_root,
            fingerprint_mode="strict"
        )
        
        assert result is True
        print(f"✓ fetch with fingerprint_mode='strict' successful")


@pytest.mark.network
@pytest.mark.slow
class TestVerifyDataFromSpec:
    """Test verify_data_from_spec() function."""
    
    def test_verify_downloads_and_validates(self, test_data_spec_path, test_backpack_root, mock_base_dir):
        """Test verify downloads and validates checksum."""
        target_root = mock_base_dir / "workflow"
        
        result = verify_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        
        assert result is True, "Verify should succeed with matching checksum"
        
        # Verify file exists
        target_file = target_root / "data" / "samples" / "diboson" / "zz" / "nano_mc2017_6.root"
        assert target_file.exists()
        print(f"✓ verify downloaded and validated file successfully")
    
    def test_verify_matching_checksum_pass(self, test_data_spec_path, test_backpack_root, mock_base_dir):
        """Test verify passes with matching checksum."""
        target_root = mock_base_dir / "workflow"
        
        result = verify_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        
        assert result is True, "Verify should pass with correct checksum"
        print(f"✓ Checksum validation passed")
    
    def test_verify_wrong_checksum_fail(self, tmp_test_dir, test_backpack_root, mock_base_dir):
        """Test verify fails with wrong checksum."""
        # Create spec with wrong checksum
        bad_checksum_spec = tmp_test_dir / "bad_checksum.yml"
        bad_checksum_spec.write_text("""
schema_version: 1.0
default_profile: bad_checksum

profiles:
  bad_checksum:
    policy:
      retry_attempts: 0
      timeout: 30
      size_tolerance_bytes: 10
    data:
      - name: test_bad_checksum
        source_type: pelican
        source: pelican://disc-head-002.crc.nd.edu:443/nd/disc2/apps/floability/examples/cms-physics-dv5/data/samples/diboson/zz/nano_mc2017_6.root
        expected_size: 190634
        checksum: sha256:0000000000000000000000000000000000000000000000000000000000000000
        target_path: data/test.root
""")
        
        target_root = mock_base_dir / "workflow"
        
        result = verify_data_from_spec(
            data_spec=str(bad_checksum_spec),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        
        assert result is False, "Verify should fail with wrong checksum"
        print(f"✓ Wrong checksum correctly detected and failed")
    
    def test_verify_size_tolerance(self, tmp_test_dir, test_backpack_root, mock_base_dir):
        """Test verify size validation with tolerance."""
        # Create spec with size tolerance
        tolerance_spec = tmp_test_dir / "size_tolerance.yml"
        tolerance_spec.write_text("""
schema_version: 1.0
default_profile: with_tolerance

profiles:
  with_tolerance:
    policy:
      retry_attempts: 0
      timeout: 30
      size_tolerance_bytes: 100
    data:
      - name: test_tolerance
        source_type: pelican
        source: pelican://disc-head-002.crc.nd.edu:443/nd/disc2/apps/floability/examples/cms-physics-dv5/data/samples/diboson/zz/nano_mc2017_6.root
        expected_size: 190700
        checksum: sha256:4c976188f38ffbd755267acb9d5b431b9208c7376afa5a26f9a62412e2f33bb0
        target_path: data/test.root
""")
        
        target_root = mock_base_dir / "workflow"
        
        result = verify_data_from_spec(
            data_spec=str(tolerance_spec),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        
        # Should pass because actual size 190634 is within tolerance of expected 190700
        assert result is True, "Verify should pass within size tolerance"
        print(f"✓ Size tolerance validation passed")
    
    def test_verify_integrity_report(self, test_data_spec_path, test_backpack_root, mock_base_dir):
        """Test verify produces integrity report output."""
        target_root = mock_base_dir / "workflow"
        
        # Capture would require redirect, so we just verify it completes
        result = verify_data_from_spec(
            data_spec=str(test_data_spec_path),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        
        assert result is True
        print(f"✓ Verify completed and produced integrity report")


@pytest.mark.network
@pytest.mark.slow
class TestExecuteDefaultDataOperation:
    """Test execute_default_data_operation() function."""
    
    def test_execute_with_policy_check(self, tmp_test_dir, test_backpack_root, mock_base_dir):
        """Test execute with policy.run_operation='check'."""
        check_spec = tmp_test_dir / "policy_check.yml"
        check_spec.write_text("""
schema_version: 1.0
default_profile: check_policy

profiles:
  check_policy:
    policy:
      run_operation: check
      retry_attempts: 0
      timeout: 30
      size_tolerance_bytes: 10
    data:
      - name: test_check
        source_type: pelican
        source: pelican://disc-head-002.crc.nd.edu:443/nd/disc2/apps/floability/examples/cms-physics-dv5/data/samples/diboson/zz/nano_mc2017_6.root
        expected_size: 190634
        target_path: data/test.root
""")
        
        result = execute_default_data_operation(
            data_spec=str(check_spec),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off",
            base_dir=mock_base_dir
        )
        
        assert result is True
        print(f"✓ execute_default_data_operation with policy='check' successful")
    
    def test_execute_with_policy_fetch(self, tmp_test_dir, test_backpack_root, mock_base_dir):
        """Test execute with policy.run_operation='fetch'."""
        fetch_spec = tmp_test_dir / "policy_fetch.yml"
        fetch_spec.write_text("""
schema_version: 1.0
default_profile: fetch_policy

profiles:
  fetch_policy:
    policy:
      run_operation: fetch
      retry_attempts: 0
      timeout: 30
      size_tolerance_bytes: 10
    data:
      - name: test_fetch
        source_type: pelican
        source: pelican://disc-head-002.crc.nd.edu:443/nd/disc2/apps/floability/examples/cms-physics-dv5/data/samples/diboson/zz/nano_mc2017_6.root
        expected_size: 190634
        target_path: data/test.root
""")
        
        target_root = mock_base_dir / "workflow"
        
        result = execute_default_data_operation(
            data_spec=str(fetch_spec),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        
        assert result is True
        
        # Verify file was fetched
        target_file = target_root / "data" / "test.root"
        assert target_file.exists()
        print(f"✓ execute_default_data_operation with policy='fetch' successful")
    
    def test_execute_with_policy_verify(self, tmp_test_dir, test_backpack_root, mock_base_dir):
        """Test execute with policy.run_operation='verify'."""
        verify_spec = tmp_test_dir / "policy_verify.yml"
        verify_spec.write_text("""
schema_version: 1.0
default_profile: verify_policy

profiles:
  verify_policy:
    policy:
      run_operation: verify
      retry_attempts: 0
      timeout: 30
      size_tolerance_bytes: 10
    data:
      - name: test_verify
        source_type: pelican
        source: pelican://disc-head-002.crc.nd.edu:443/nd/disc2/apps/floability/examples/cms-physics-dv5/data/samples/diboson/zz/nano_mc2017_6.root
        expected_size: 190634
        checksum: sha256:4c976188f38ffbd755267acb9d5b431b9208c7376afa5a26f9a62412e2f33bb0
        target_path: data/test.root
""")
        
        target_root = mock_base_dir / "workflow"
        
        result = execute_default_data_operation(
            data_spec=str(verify_spec),
            backpack_root=test_backpack_root,
            verbose=True,
            data_cache_mode="off",
            base_dir=mock_base_dir,
            target_root=target_root
        )
        
        assert result is True
        print(f"✓ execute_default_data_operation with policy='verify' successful")
