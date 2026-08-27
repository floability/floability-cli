# Directory Download Support - Design Document

## Problem Statement

Currently, the data handler treats all sources as individual files. When a user specifies a directory URL (e.g., `pelican://server/path/to/dir/`), the system:
1. Tries to download it as a single file
2. Creates a file named after the target_path instead of a directory with contents

**Example problematic spec:**
```yaml
- name: data_dir
  source_type: pelican  
  source: pelican://disc-head-002.crc.nd.edu:443/nd/disc2/apps/floability/examples/cms-physics-dv5/data/
  target_path: data
```

**Current behavior:** Creates a single file `data`  
**Expected behavior:** Creates directory `data/` with all files from remote directory recursively

## Root Causes

1. **No directory detection**: System doesn't check if source is file or directory
2. **No recursive download function**: `pelican_file_download()` only handles single files  
3. **No directory listing function**: No way to recursively list Pelican directory contents
4. **No spec field to indicate directory**: No `is_directory` or similar field

## Proposed Solution

### 1. Add Directory Detection

**Option A: Explicit field** (Recommended for clarity)
- Add optional `source_object_type` field with values: `"file"`, `"directory"`
- If specified, skips auto-detection
- Pros: Explicit, no network call, clear intent, works for all source types
- Cons: Requires user to specify

**Option B: URL-based heuristic** (Simple, fast)
- If URL ends with `/`, treat as directory
- Pros: No network call needed, clear intent
- Cons: User must remember trailing slash

**Option C: Metadata-based detection** (More robust)
- Call `fs.info(path)` and check `type` field
- If `type == 'directory'`, it's a directory
- Pros: Works regardless of URL format
- Cons: Extra network call

**Recommendation: Use all three with priority order**
1. Check `source_object_type` field first (if present)
2. Check for trailing `/` in URL
3. Call `is_pelican_directory()` as fallback (metadata check)

### 2. Add Pelican Directory Listing Function

```python
def pelican_list_directory(url: str, recursive: bool = True) -> List[Dict[str, Any]]:
    """
    List all files in a Pelican directory.
    
    Args:
        url: Pelican directory URL (e.g., pelican://server/path/to/dir/)
        recursive: If True, list all files recursively
    
    Returns:
        List of dicts with keys: path, size, type, name
    """
```

Implementation using PelicanFileSystem:
- `fs.ls(path, detail=True)` - list directory with details
- `fs.walk(path)` - recursive traversal
- Filter out directories, return only files

### 3. Add Pelican Directory Download Function

```python
def pelican_directory_download(
    url: str,
    dest_dir: str = ".",
    *,
    overwrite: bool = False,
    show_progress: bool = True,
) -> Path:
    """
    Download all files from a Pelican directory recursively.
    
    Args:
        url: Pelican directory URL
        dest_dir: Local destination directory  
        overwrite: Overwrite existing files
        show_progress: Show progress bar
    
    Returns:
        Path to destination directory
    """
```

Implementation:
1. List all files recursively using `pelican_list_directory()`
2. For each file, download using `pelican_file_download()`
3. Preserve directory structure in dest_dir
4. Optional: aggregate progress across all files

### 4. Update Data Handler Logic

In `_fetch_source_to_target()`:

```python
if stype == "pelican":
    # Check if source is a directory
    if src.endswith('/') or _is_pelican_directory(src):
        # Directory download
        pelican_directory_download(
            src,
            dest_dir=str(target_path),
            overwrite=force,
        )
    else:
        # Single file download
        pelican_file_download(
            src,
            dest_dir=str(target_path.parent),
            filename=target_path.name,
            overwrite=force,
        )
    return True
```

### 5. Add Spec Field for Explicit Control

Add optional field to data item:
```yaml
- name: data_dir
  source_type: pelican
  source: pelican://server/path/to/dir/
  target_path: data
  source_object_type: directory  # Optional: "file" or "directory"
```

**Benefits:**
- Explicit control over file vs directory handling
- Avoids auto-detection overhead (no network metadata call)
- Works for ambiguous URLs (no trailing slash needed)
- Self-documenting spec

**Implementation:**
- Priority order: `source_object_type` → URL trailing `/` → metadata check
- Valid values: `"file"`, `"directory"`, or omitted for auto-detect
- Applied to both direct fetch and cache build paths

### 6. Extend to Other Source Types

Apply same pattern to:
- **S3**: Add `s3_directory_download()` using `s3_list_objects(recursive=True)`
- **HTTP**: Limited support (requires directory listing endpoint)
- **FS/Backpack**: Already supported via `shutil.copytree()`

## Implementation Plan

### Phase 1: Pelican Directory Support (This PR)
1. ✅ Add `pelican_list_directory()` to `pelican_file_utils.py`
2. ✅ Add `pelican_directory_download()` to `pelican_file_utils.py`  
3. ✅ Update `_fetch_source_to_target()` to detect and handle directories
4. ✅ Add tests for directory operations
5. ✅ Update documentation

### Phase 2: S3 Directory Support (Future)
1. Add `s3_directory_download()` using existing `s3_list_objects()`
2. Update data handler to handle S3 directories
3. Add tests

### Phase 3: Metadata & Verification (Future)
1. Support `expected_size` for directories (sum of all files)
2. Support checksums for directories (manifest-based)
3. Cache directory downloads as units

## Testing Strategy

1. **Unit tests**: Test directory listing and download functions
2. **Integration tests**: Test with real Pelican server
3. **Edge cases**:
   - Empty directories
   - Nested directories
   - Large directories (many files)
   - Partial downloads/resume
   - Permission errors

## Migration Path

- **Backward compatible**: Existing single-file specs work unchanged
- **Opt-in**: Users add trailing `/` to enable directory mode
- **No breaking changes**: All existing functionality preserved
