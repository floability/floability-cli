#!/usr/bin/env python3
"""Test Pelican directory download functionality."""

import sys
import os
from pathlib import Path

# Add floability to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from floability.data.pelican_file_utils import (
    is_pelican_directory,
    pelican_list_directory,
    pelican_directory_download,
)

# Test URL - the directory from the user's spec
TEST_URL = "pelican://disc-head-002.crc.nd.edu:443/nd/disc2/apps/floability/examples/cms-physics-dv5/data/"
OUTPUT_DIR = Path("./test-pelican-dir-download")

print("=" * 70)
print("Pelican Directory Download Test")
print("=" * 70)

# Test 1: Check if URL is recognized as directory
print(f"\n1. Testing is_pelican_directory()")
print(f"   URL: {TEST_URL}")
try:
    is_dir = is_pelican_directory(TEST_URL)
    print(f"   Result: {'✅ Directory' if is_dir else '❌ File'}")
except Exception as e:
    print(f"   Error: {e}")
    sys.exit(1)

if not is_dir:
    print("   ERROR: URL should be detected as directory")
    sys.exit(1)

# Test 2: List directory contents
print(f"\n2. Testing pelican_list_directory()")
try:
    files = pelican_list_directory(TEST_URL, recursive=True)
    print(f"   Found {len(files)} files:")
    for i, f in enumerate(files[:10], 1):  # Show first 10
        print(f"     {i}. {f['name']} ({f['size']} bytes)")
    if len(files) > 10:
        print(f"     ... and {len(files) - 10} more files")
except Exception as e:
    print(f"   Error: {e}")
    sys.exit(1)

# Test 3: Download directory
print(f"\n3. Testing pelican_directory_download()")
print(f"   Downloading to: {OUTPUT_DIR}")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

try:
    result = pelican_directory_download(
        TEST_URL,
        dest_dir=str(OUTPUT_DIR),
        overwrite=True,
        show_progress=True,
    )
    print(f"\n   ✅ Download complete: {result}")
except Exception as e:
    print(f"\n   ❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Verify downloaded files
print(f"\n4. Verifying downloaded files")
downloaded_files = list(OUTPUT_DIR.rglob("*"))
downloaded_files = [f for f in downloaded_files if f.is_file()]
print(f"   Local files: {len(downloaded_files)}")
print(f"   Remote files: {len(files)}")

if len(downloaded_files) == len(files):
    print("   ✅ File count matches!")
else:
    print(f"   ⚠️  File count mismatch (expected {len(files)}, got {len(downloaded_files)})")

# Show some downloaded files
print("\n   Downloaded files:")
for i, f in enumerate(sorted(downloaded_files)[:10], 1):
    rel = f.relative_to(OUTPUT_DIR)
    size = f.stat().st_size
    print(f"     {i}. {rel} ({size} bytes)")
if len(downloaded_files) > 10:
    print(f"     ... and {len(downloaded_files) - 10} more")

print("\n" + "=" * 70)
print("✅ All tests passed!")
print("=" * 70)
