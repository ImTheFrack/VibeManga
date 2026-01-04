# Smart Merge Feature - Implementation Summary

## Overview

The dedupe merge functionality has been enhanced with **smart renaming** that automatically renames files to match the target series naming convention during merge operations.

## Problem Solved

**Before**: When merging "One Piece Definitive Edition v01" into "One Piece", files were copied with their original names, resulting in:
- `One Piece Definitive Edition v01.cbz` (source)
- `One Piece v01.cbz` (target existing)
- After merge: Both files exist with different names = not truly merged

**After**: Files are automatically renamed to match target series pattern:
- `One Piece Definitive Edition v01.cbz` → `One Piece v01.cbz`
- Properly merges into target series structure

## Features Implemented

### 1. Automatic Pattern Detection

**Function**: `_detect_series_naming_pattern()`

Detects the naming convention used by the target series:
- **Base name**: Series name (e.g., "One Piece")
- **Unit format**: Pattern for volumes/chapters (e.g., "v{:02d}", "c{:03d}")
- **Subgroup**: Appropriate subfolder if series uses subgroups

**Detection Logic**:
- Scans existing files in target series
- Identifies volume (`v01`, `v02`), chapter (`c001`, `c123`), or unit (`unit0001`) patterns
- Detects leading zero padding (e.g., `v01` vs `v1`)
- Falls back to defaults if no pattern found

### 2. Smart Filename Generation

**Function**: `_generate_target_filename()`

Generates correct target filename by:
1. Extracting unit numbers from source filename using `classify_unit()`
2. Formatting unit numbers according to target pattern
3. Combining with target series base name

**Examples**:
```
Source: "One Piece Definitive Edition v01.cbz"
Target pattern: "One Piece" + "v{:02d}"
Result: "One Piece v01.cbz"

Source: "OP c001.cbz" 
Target pattern: "One Piece" + "c{:03d}"
Result: "One Piece c001.cbz"

Source: "Naruto v10.cbz"
Target pattern: "Naruto" + "v{}"
Result: "Naruto v10.cbz"
```

### 3. Subgroup Awareness

When merging into series with subgroups (e.g., "One Piece v01-v110", "One Piece v111+"):
- Automatically detects appropriate subgroup based on unit numbers
- Places files in correct subfolder
- Maintains existing organization structure

### 4. Enhanced Merge Execution

**Updated**: `_move_series_files()` in `dedupe_actions.py`

Now includes:
- Pattern detection before moving files
- Filename generation for each file
- Real-time display of rename operations
- Proper conflict resolution with renamed files

## Usage

### Interactive Merge

```bash
python -m vibe_manga.run dedupe

# When prompted for a duplicate:
# Select [M]erge
# Choose target series (primary)
# Files automatically renamed to match target pattern
```

### Example Session

```
MAL ID CONFLICT DETECTED: 13
Series 1: One Piece Definitive Edition (24 volumes)
Series 2: One Piece (187 volumes)

How would you like to resolve this?
> merge

Primary series selected: One Piece
Target: Manga/Shounen/One Piece

Renaming files during merge:
  One Piece Definitive Edition v01.cbz -> One Piece v01.cbz
  One Piece Definitive Edition v02.cbz -> One Piece v02.cbz
  ...
  One Piece Definitive Edition v24.cbz -> One Piece v24.cbz

Merged 24 files into One Piece
```

## Technical Details

### Pattern Detection Algorithm

1. **Scan target directory** for existing manga files
2. **Analyze first matching file** to extract pattern:
   - Use regex to find `v(\d+)`, `c(\d+)`, or `unit(\d+)`
   - Check for leading zeros to determine padding
3. **Return pattern components**: base_name, unit_format, subgroup_path

### Filename Generation Algorithm

1. **Parse source filename** with `classify_unit()` to extract (volumes, chapters, units)
2. **Select primary unit number** (first in list)
3. **Format number** according to target pattern:
   - Extract numeric component
   - Apply formatting (with or without leading zeros)
4. **Construct new filename**: `{base_name} {formatted_unit}{extension}`

### Supported Patterns

- **Volumes**: `v1`, `v01`, `v001` → `v{}`, `v{:02d}`, `v{:03d}`
- **Chapters**: `c1`, `c001`, `c123` → `c{}`, `c{:03d}`
- **Units**: `unit1`, `unit0001` → `unit{}`, `unit{:04d}`
- **Decimals**: `v01.5`, `c100.5` (automatically preserved)

## Test Results

All tests pass (7/7):

```
✓ One Piece Definitive Edition v01.cbz → One Piece v01.cbz
✓ One Piece Definitive Edition v24.cbz → One Piece v24.cbz
✓ OP c001.cbz → One Piece c001.cbz
✓ OP c123.cbz → One Piece c123.cbz
✓ OnePiece unit0001.cbz → One Piece unit0001.cbz
✓ Naruto v1.cbz → Naruto v1.cbz
✓ Naruto v10.cbz → Naruto v10.cbz
```

## Files Modified

1. **`dedupe_actions.py`** (added ~125 lines):
   - `_get_series_name_from_path()` - Extract series name
   - `_detect_series_naming_pattern()` - Detect target pattern
   - `_generate_target_filename()` - Generate renamed filename
   - Updated `_move_series_files()` - Use smart renaming

## Benefits

1. **Seamless Integration**: Files truly merge into target series
2. **Consistent Naming**: All files follow same convention after merge
3. **Preserves Organization**: Respects subgroups and folder structure
4. **Automatic**: No manual renaming required
5. **Flexible**: Works with any naming pattern (volumes, chapters, units)

## Future Enhancements

Potential improvements:
- Detect and preserve additional metadata in filenames (e.g., version tags)
- Handle multi-unit files (e.g., `v01-02`)
- Support for language codes in filenames
- Configurable rename patterns per series
