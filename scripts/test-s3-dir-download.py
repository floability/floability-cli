#!/usr/bin/env python3
"""
Test script for S3 directory download and caching.

Tests the S3 directory download feature using s3://floability/dv5-sample-data/

Requirements:
    - Run in floability-env conda environment
    - Requires boto3 package
    - May require AWS credentials or anonymous access
"""

import sys
import tempfile
from pathlib import Path

# Add floability to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from floability.data.s3_file_utils import (
    is_s3_directory,
    s3_list_objects,
    s3_directory_download,
)


def test_s3_directory_detection():
    """Test S3 directory detection."""
    print("\n" + "=" * 60)
    print("Test 1: S3 Directory Detection")
    print("=" * 60)
    
    test_uri = "s3://floability/dv5-sample-data/"
    
    print(f"\nChecking if {test_uri} is a directory...")
    try:
        is_dir = is_s3_directory(test_uri, anonymous=True)
        print(f"✅ is_s3_directory returned: {is_dir}")
        return is_dir
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_s3_list_objects():
    """Test listing S3 objects in a directory."""
    print("\n" + "=" * 60)
    print("Test 2: S3 List Objects")
    print("=" * 60)
    
    test_uri = "s3://floability/dv5-sample-data/"
    
    print(f"\nListing objects in {test_uri}...")
    try:
        objects = s3_list_objects(test_uri, recursive=True, anonymous=True)
        print(f"✅ Found {len(objects)} objects")
        
        if objects:
            print("\nFirst few objects:")
            for obj in objects[:5]:
                size_mb = obj.get('size', 0) / (1024 * 1024) if obj.get('size') else 0
                print(f"  - {obj.get('key', 'unknown')} ({size_mb:.2f} MB)")
            
            if len(objects) > 5:
                print(f"  ... and {len(objects) - 5} more")
        
        return len(objects) > 0
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_s3_directory_download():
    """Test downloading an S3 directory."""
    print("\n" + "=" * 60)
    print("Test 3: S3 Directory Download")
    print("=" * 60)
    
    test_uri = "s3://floability/dv5-sample-data/"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        dest_dir = Path(tmpdir) / "downloaded"
        
        print(f"\nDownloading {test_uri} to {dest_dir}...")
        try:
            result = s3_directory_download(
                test_uri,
                dest_dir=str(dest_dir),
                overwrite=True,
                show_progress=True,
                anonymous=True,
            )
            
            print(f"\n✅ Download completed to {result}")
            
            # List downloaded files
            if result.exists():
                downloaded_files = list(result.rglob("*"))
                file_count = sum(1 for f in downloaded_files if f.is_file())
                dir_count = sum(1 for f in downloaded_files if f.is_dir())
                
                print(f"\nDownloaded structure:")
                print(f"  - {file_count} files")
                print(f"  - {dir_count} directories")
                
                # Show first few files
                files = [f for f in downloaded_files if f.is_file()][:5]
                if files:
                    print(f"\nFirst few files:")
                    for f in files:
                        rel_path = f.relative_to(result)
                        size_kb = f.stat().st_size / 1024
                        print(f"  - {rel_path} ({size_kb:.2f} KB)")
                
                return file_count > 0
            else:
                print(f"❌ Destination directory doesn't exist: {result}")
                return False
                
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False


def test_s3_caching_with_data_handler():
    """Test S3 directory caching using data_handler."""
    print("\n" + "=" * 60)
    print("Test 4: S3 Directory Caching with Data Handler")
    print("=" * 60)
    
    from floability.data.data_handler import _build_cache_entry, _lookup_cache_entry
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "cache"
        cache_dir.mkdir()
        
        # Create test item
        item = {
            'name': 'dv5_data',
            'target_location': 'data/dv5',
            'source': 's3://floability/dv5-sample-data/',
            'source_type': 's3',
            'source_object_type': 'directory',
        }
        
        print(f"\nBuilding cache entry for {item['source']}...")
        try:
            success = _build_cache_entry(
                item=item,
                cache_dir=cache_dir,
                backpack_root=Path(tmpdir),
                verbose=True,
            )
            
            if not success:
                print("❌ Failed to build cache entry")
                return False
            
            print(f"✅ Cache entry built successfully")
            
            # Check cache structure
            cached_data_dir = cache_dir / "cached_data"
            if not cached_data_dir.exists():
                print(f"❌ cached_data directory doesn't exist at {cached_data_dir}")
                return False
            
            print(f"✅ cached_data directory exists")
            
            # Check structure
            expected_path = cached_data_dir / "data" / "dv5"
            if expected_path.exists():
                print(f"✅ Data cached at correct path: {expected_path}")
                
                # Count files
                files = list(expected_path.rglob("*"))
                file_count = sum(1 for f in files if f.is_file())
                print(f"   Found {file_count} files in cache")
                
                return file_count > 0
            else:
                print(f"❌ Expected path doesn't exist: {expected_path}")
                print(f"   Cache structure:")
                for p in cached_data_dir.rglob("*"):
                    print(f"     {p.relative_to(cached_data_dir)}")
                return False
                
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    """Run all S3 directory download tests."""
    print("=" * 60)
    print("S3 Directory Download Tests")
    print("=" * 60)
    print("\nTest URL: s3://floability/dv5-sample-data/")
    print("Access mode: Anonymous (public bucket)")
    print("\nNote: Requires boto3 package")
    print("=" * 60)
    
    results = {}
    
    # Test 1: Directory detection
    results['detection'] = test_s3_directory_detection()
    
    # Test 2: List objects
    results['list'] = test_s3_list_objects()
    
    # Test 3: Directory download
    results['download'] = test_s3_directory_download()
    
    # Test 4: Caching with data handler
    results['caching'] = test_s3_caching_with_data_handler()
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:20s}: {status}")
    
    print("=" * 60)
    
    all_passed = all(results.values())
    if all_passed:
        print("\n✅ ALL TESTS PASSED")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
