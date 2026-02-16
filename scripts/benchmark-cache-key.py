#!/usr/bin/env python3
"""
Benchmark script for data cache key generation.

Tests all three fingerprint modes (meta, sample, strict) on a given file or directory
and generates a performance report.

Usage:
    python scripts/benchmark-cache-key.py <path>
    python scripts/benchmark-cache-key.py <path> --sample-bytes 1024
    python scripts/benchmark-cache-key.py <path> --verbose
"""

import sys
import time
import json
from pathlib import Path
from datetime import datetime

# Add parent directory to path to import floability modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from floability.data.fingerprint import compute_fingerprint
from floability.data.data_handler import _compute_cache_key, _create_artifact_spec


def format_size(size_bytes):
    """Format size in bytes to human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def format_time(seconds):
    """Format time in seconds to human-readable format."""
    if seconds < 1:
        return f"{seconds * 1000:.2f} ms"
    elif seconds < 60:
        return f"{seconds:.2f} s"
    else:
        minutes = int(seconds / 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.2f}s"


def get_path_info(path):
    """Get basic information about the path."""
    path_obj = Path(path)
    
    if not path_obj.exists():
        return None
    
    if path_obj.is_file():
        size = path_obj.stat().st_size
        return {
            "type": "file",
            "size": size,
            "size_formatted": format_size(size),
            "name": path_obj.name,
        }
    elif path_obj.is_dir():
        # Count files and total size
        total_size = 0
        file_count = 0
        for item in path_obj.rglob("*"):
            if item.is_file():
                total_size += item.stat().st_size
                file_count += 1
        
        return {
            "type": "directory",
            "size": total_size,
            "size_formatted": format_size(total_size),
            "file_count": file_count,
            "name": path_obj.name,
        }
    else:
        return None


def benchmark_fingerprint(path, mode, sample_bytes=200, verbose=False):
    """Benchmark fingerprint computation for a given mode."""
    start_time = time.time()
    
    try:
        result = compute_fingerprint(
            path,
            mode=mode,
            sample_bytes=sample_bytes,
            verbose=verbose
        )
        
        elapsed = time.time() - start_time
        
        return {
            "success": True,
            "fingerprint": result.get("fingerprint"),
            "mode": result.get("mode"),
            "params": result.get("params"),
            "elapsed_seconds": elapsed,
            "elapsed_formatted": format_time(elapsed),
        }
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "success": False,
            "error": str(e),
            "elapsed_seconds": elapsed,
            "elapsed_formatted": format_time(elapsed),
        }


def benchmark_cache_key(path, backpack_root=None, sample_bytes=200, verbose=False):
    """
    Benchmark cache key generation for all three fingerprint modes.
    
    Args:
        path: Path to file or directory
        backpack_root: Base path for resolving relative paths (default: parent of path)
        sample_bytes: Number of bytes to sample in sample mode
        verbose: Print detailed progress
    
    Returns:
        Dict with benchmark results
    """
    path_obj = Path(path).resolve()
    
    if not path_obj.exists():
        print(f"ERROR: Path does not exist: {path}")
        return None
    
    if backpack_root is None:
        backpack_root = path_obj.parent
    
    # Get path info
    path_info = get_path_info(path)
    if path_info is None:
        print(f"ERROR: Invalid path type: {path}")
        return None
    
    print("=" * 70)
    print(f"CACHE KEY BENCHMARK: {path_obj.name}")
    print("=" * 70)
    print(f"Path: {path_obj}")
    print(f"Type: {path_info['type']}")
    print(f"Size: {path_info['size_formatted']}")
    if path_info['type'] == 'directory':
        print(f"Files: {path_info['file_count']}")
    print()
    
    # Create a mock artifact spec (used for cache key computation)
    artifact_spec_base = {
        "source_type": "fs",
        "source": str(path_obj),
        "target_location": f"data/{path_obj.name}",
    }
    
    results = {
        "path": str(path_obj),
        "path_info": path_info,
        "timestamp": datetime.now().isoformat(),
        "modes": {},
    }
    
    # Benchmark each mode
    modes = ["meta", "sample", "strict"]
    
    for mode in modes:
        print(f"[{mode.upper()}] Computing fingerprint...")
        
        # Benchmark fingerprint computation
        fp_result = benchmark_fingerprint(
            str(path_obj),
            mode=mode,
            sample_bytes=sample_bytes,
            verbose=verbose
        )
        
        if not fp_result["success"]:
            print(f"  ❌ ERROR: {fp_result['error']}")
            print(f"  Time: {fp_result['elapsed_formatted']}")
            print()
            results["modes"][mode] = {
                "fingerprint_result": fp_result,
                "cache_key": None,
                "total_time": fp_result["elapsed_seconds"],
            }
            continue
        
        # Create artifact spec with fingerprint info
        artifact_spec = artifact_spec_base.copy()
        artifact_spec["fingerprint"] = fp_result["fingerprint"]
        artifact_spec["fingerprint_mode"] = mode
        
        # Benchmark cache key computation
        cache_key_start = time.time()
        cache_key = _compute_cache_key(artifact_spec)
        cache_key_elapsed = time.time() - cache_key_start
        
        total_time = fp_result["elapsed_seconds"] + cache_key_elapsed
        
        # Calculate throughput
        if path_info['type'] == 'file':
            throughput_mbps = path_info['size'] / (1024 * 1024) / fp_result["elapsed_seconds"]
        elif path_info['type'] == 'directory':
            throughput_mbps = path_info['size'] / (1024 * 1024) / fp_result["elapsed_seconds"]
        else:
            throughput_mbps = 0
        
        print(f"  ✓ Fingerprint: {fp_result['fingerprint'][:16]}...")
        print(f"  ✓ Cache key:   {cache_key[:16]}...")
        print(f"  Time (fingerprint): {fp_result['elapsed_formatted']}")
        print(f"  Time (cache key):   {format_time(cache_key_elapsed)}")
        print(f"  Time (total):       {format_time(total_time)}")
        print(f"  Throughput:         {throughput_mbps:.2f} MB/s")
        print()
        
        results["modes"][mode] = {
            "fingerprint_result": fp_result,
            "cache_key": cache_key,
            "cache_key_time": cache_key_elapsed,
            "total_time": total_time,
            "throughput_mbps": throughput_mbps,
        }
    
    # Print comparison summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Path:  {path_obj}")
    print(f"Type:  {path_info['type']}")
    print(f"Size:  {path_info['size_formatted']} ({path_info['size']:,} bytes)")
    if path_info['type'] == 'directory':
        print(f"Files: {path_info['file_count']}")
    print()
    print(f"{'Mode':<10} {'Time':<15} {'Throughput':<15} {'Speedup':<10}")
    print("-" * 70)
    
    # Use strict as baseline for speedup calculation
    baseline_time = results["modes"].get("strict", {}).get("total_time", 1.0)
    
    for mode in modes:
        if mode not in results["modes"]:
            continue
        
        mode_data = results["modes"][mode]
        total_time = mode_data.get("total_time", 0)
        throughput = mode_data.get("throughput_mbps", 0)
        speedup = baseline_time / total_time if total_time > 0 else 0
        
        print(f"{mode:<10} {format_time(total_time):<15} {throughput:.2f} MB/s    {speedup:.1f}x")
    
    print()
    
    # Save detailed report
    report_file = Path.cwd() / f"cache-key-report-{path_obj.name}-{int(time.time())}.json"
    with open(report_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"Detailed report saved to: {report_file}")
    print()
    
    return results


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Benchmark data cache key generation with different fingerprint modes"
    )
    parser.add_argument(
        "path",
        help="Path to file or directory to benchmark"
    )
    parser.add_argument(
        "--sample-bytes",
        type=int,
        default=200,
        help="Number of bytes to sample in sample mode (default: 200)"
    )
    parser.add_argument(
        "--backpack-root",
        help="Base path for resolving relative paths (default: parent of path)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed progress during fingerprinting"
    )
    
    args = parser.parse_args()
    
    results = benchmark_cache_key(
        path=args.path,
        backpack_root=args.backpack_root,
        sample_bytes=args.sample_bytes,
        verbose=args.verbose
    )
    
    if results is None:
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
