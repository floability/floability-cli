#!/usr/bin/env python3
"""
Quick verification script for fingerprinting implementation.
Tests that all components are properly connected.
"""

import sys
from pathlib import Path

# Import the source checkout when the script is run before installation.
repository_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository_root / "src"))

print("=" * 70)
print("Floability Fingerprinting Implementation Verification")
print("=" * 70)

# Test 1: Import fingerprint module
print("\n[1/5] Testing fingerprint module import...")
try:
    from floability.data.fingerprint import compute_fingerprint
    print("✅ fingerprint module imported successfully")
except ImportError as e:
    print(f"❌ Failed to import fingerprint module: {e}")
    sys.exit(1)

# Test 2: Import data_handler updates
print("\n[2/5] Testing data_handler integration...")
try:
    from floability.data.data_handler import (
        execute_default_data_operation,
        fetch_data_from_spec,
        verify_data_from_spec,
    )
    print("✅ data_handler functions imported successfully")
except ImportError as e:
    print(f"❌ Failed to import data_handler: {e}")
    sys.exit(1)

# Test 3: Check function signatures
print("\n[3/5] Checking function signatures...")
import inspect

# Check execute_default_data_operation has fingerprint_mode parameter
sig = inspect.signature(execute_default_data_operation)
if 'fingerprint_mode' in sig.parameters:
    print("✅ execute_default_data_operation has fingerprint_mode parameter")
else:
    print("❌ execute_default_data_operation missing fingerprint_mode parameter")
    sys.exit(1)

# Check fetch_data_from_spec has fingerprint_mode parameter
sig = inspect.signature(fetch_data_from_spec)
if 'fingerprint_mode' in sig.parameters:
    print("✅ fetch_data_from_spec has fingerprint_mode parameter")
else:
    print("❌ fetch_data_from_spec missing fingerprint_mode parameter")
    sys.exit(1)

# Check verify_data_from_spec has fingerprint_mode parameter
sig = inspect.signature(verify_data_from_spec)
if 'fingerprint_mode' in sig.parameters:
    print("✅ verify_data_from_spec has fingerprint_mode parameter")
else:
    print("❌ verify_data_from_spec missing fingerprint_mode parameter")
    sys.exit(1)

# Test 4: Test fingerprint computation
print("\n[4/5] Testing fingerprint computation...")
import tempfile
import os

# Create a test file
test_dir = Path(tempfile.mkdtemp(prefix='flo_verify_'))
test_file = test_dir / "test.txt"
test_file.write_text("Test content for verification\n")

try:
    # Test all three modes
    for mode in ['meta', 'sample', 'strict']:
        result = compute_fingerprint(str(test_file), mode, verbose=False)
        assert 'fingerprint' in result, f"Missing fingerprint in {mode} result"
        assert 'mode' in result, f"Missing mode in {mode} result"
        assert 'params' in result, f"Missing params in {mode} result"
        assert result['mode'] == mode, f"Mode mismatch: expected {mode}, got {result['mode']}"
        print(f"  ✅ {mode} mode: {result['fingerprint'][:16]}...")
    
    print("✅ Fingerprint computation working correctly")
except Exception as e:
    print(f"❌ Fingerprint computation failed: {e}")
    sys.exit(1)
finally:
    # Cleanup
    import shutil
    shutil.rmtree(test_dir)

# Test 5: Test directory fingerprinting
print("\n[5/5] Testing directory fingerprinting...")
test_dir = Path(tempfile.mkdtemp(prefix='flo_verify_dir_'))
(test_dir / "file1.txt").write_text("Content 1\n")
(test_dir / "file2.txt").write_text("Content 2\n")
subdir = test_dir / "subdir"
subdir.mkdir()
(subdir / "file3.txt").write_text("Content 3\n")

try:
    for mode in ['meta', 'sample', 'strict']:
        result = compute_fingerprint(str(test_dir), mode, verbose=False)
        assert 'fingerprint' in result
        assert result['mode'] == mode
        print(f"  ✅ {mode} mode: {result['fingerprint'][:16]}...")
    
    print("✅ Directory fingerprinting working correctly")
except Exception as e:
    print(f"❌ Directory fingerprinting failed: {e}")
    sys.exit(1)
finally:
    import shutil
    shutil.rmtree(test_dir)

# Final summary
print("\n" + "=" * 70)
print("✅ All verification tests passed!")
print("=" * 70)
print("\nImplementation is ready for testing with floability commands.")
print("\nNext steps:")
print("  1. Review TEST_FINGERPRINTING.md for comprehensive test scenarios")
print("  2. Run: floability data --help (to see --fingerprint-mode option)")
print("  3. Run: floability run --help (to see --fingerprint-mode option)")
print("  4. Test with example backpacks")
print("=" * 70)
