#!/usr/bin/env python3
"""
Test script to verify the new cache structure with 'cached_data' directory.
"""

import sys
import tempfile
from pathlib import Path

# Add floability to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from floability.data.data_handler import _build_cache_entry, _lookup_cache_entry, _materialize_from_cache


def test_cache_structure():
    """Test that cache uses 'cached_data' directory and preserves target_location structure."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "cache"
        cache_dir.mkdir()
        
        # Create a simple test file
        test_data_dir = Path(tmpdir) / "source_data"
        test_data_dir.mkdir(parents=True)
        test_file = test_data_dir / "test.txt"
        test_file.write_text("Hello from test file!")
        
        # Test item with nested target_location
        item = {
            'name': 'test_file',
            'target_location': 'data/samples/test.txt',
            'source': str(test_file),
            'source_type': 'filesystem'
        }
        
        # Build cache entry
        print("Building cache entry...")
        success = _build_cache_entry(
            item=item,
            cache_dir=cache_dir,
            backpack_root=Path(tmpdir),
            verbose=True,
        )
        
        if not success:
            print("❌ Failed to build cache entry")
            return False
        
        # Check cache structure
        cached_data_dir = cache_dir / "cached_data"
        if not cached_data_dir.exists():
            print(f"❌ cached_data directory doesn't exist at {cached_data_dir}")
            return False
        
        print(f"✅ cached_data directory exists at {cached_data_dir}")
        
        # Check that file is stored with full target_location path
        expected_path = cached_data_dir / "data" / "samples" / "test.txt"
        if not expected_path.exists():
            print(f"❌ Expected file not found at {expected_path}")
            print(f"   Cache structure:")
            for p in cached_data_dir.rglob("*"):
                print(f"     {p.relative_to(cached_data_dir)}")
            return False
        
        print(f"✅ File stored correctly at {expected_path}")
        
        # Verify content
        content = expected_path.read_text()
        if content != "Hello from test file!":
            print(f"❌ Content mismatch: {content}")
            return False
        
        print(f"✅ File content preserved correctly")
        
        # Check metadata
        meta_file = cache_dir / ".meta.json"
        if not meta_file.exists():
            print(f"❌ Metadata file doesn't exist at {meta_file}")
            return False
        
        print(f"✅ Metadata file exists at {meta_file}")
        
        # Test lookup
        print("\nTesting cache lookup...")
        cache_meta = _lookup_cache_entry(cache_dir, verbose=True)
        if cache_meta is None:
            print("❌ Cache lookup failed")
            return False
        
        print(f"✅ Cache lookup successful")
        
        # Test materialization
        print("\nTesting materialization...")
        workflow_dir = Path(tmpdir) / "workflow"
        workflow_dir.mkdir()
        
        success = _materialize_from_cache(
            cache_dir=cache_dir,
            workflow_dir=workflow_dir,
            target_location=item['target_location'],
            verbose=True
        )
        
        if not success:
            print("❌ Materialization failed")
            return False
        
        # Check materialized location
        materialized_file = workflow_dir / "data" / "samples" / "test.txt"
        if not materialized_file.exists():
            print(f"❌ Materialized file not found at {materialized_file}")
            print(f"   Workflow structure:")
            for p in workflow_dir.rglob("*"):
                print(f"     {p.relative_to(workflow_dir)}")
            return False
        
        print(f"✅ File materialized correctly at {materialized_file}")
        
        # Verify materialized content
        content = materialized_file.read_text()
        if content != "Hello from test file!":
            print(f"❌ Materialized content mismatch: {content}")
            return False
        
        print(f"✅ Materialized file content correct")
        
        return True


if __name__ == "__main__":
    print("=" * 60)
    print("Testing new cache structure with 'cached_data' directory")
    print("=" * 60)
    
    try:
        success = test_cache_structure()
        
        print("\n" + "=" * 60)
        if success:
            print("✅ ALL TESTS PASSED")
            print("=" * 60)
            sys.exit(0)
        else:
            print("❌ TESTS FAILED")
            print("=" * 60)
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
