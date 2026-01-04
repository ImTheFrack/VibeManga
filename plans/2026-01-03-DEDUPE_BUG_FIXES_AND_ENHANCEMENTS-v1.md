# VibeManga Dedupe Bug Fixes and Enhancements

## Critical Bugs to Fix

### Bug 1: MAL ID Duplicates Not Detected
**Issue**: Indexer warnings show duplicate MAL IDs exist, but dedupe engine reports "Found 0 MAL ID conflicts"

**Root Cause Analysis**:
- Indexer detects duplicates during scan (line 99-101 in indexer.py)
- But MALIDDuplicateDetector may not be finding them due to:
  1. Series objects without MAL IDs when detector runs
  2. Logic error in duplicate group creation
  3. Filtering or state issues

**Fix Required**:
- Add debug logging to trace MAL ID detection
- Ensure series.mal_id is accessible and correctly typed
- Verify mal_id_map population logic
- Add diagnostic output to help users understand what's being scanned

### Bug 2: Insufficient Information During Resolution
**Issue**: When presenting duplicates, only shows "Affected Series: Issak" without paths, files, or details

**Current Insufficient Display**:
```
Affected Series: Issak
Resolution Options: [M]erge [D]elete [S]kip
```

**Required Enhanced Display**:
```
Duplicate Group: MAL ID Conflict (ID: 12345)
Confidence: 95%

Series 1: Issak
  Path: Manga/Shounen/Issak
  Volumes: 15 files (8.2 GB)
  Categories: Action, Drama
  MAL ID: 12345
  Date Added: 2024-01-15

Series 2: Issak (Comic)
  Path: Manga/Comedy/Issak Comic
  Volumes: 12 files (6.1 GB)
  Categories: Comedy, Slice of Life
  MAL ID: 12345
  Date Added: 2024-03-22

File Comparison:
  Series 1 has 3 volumes Series 2 doesn't: v13, v14, v15
  Series 2 has all volumes from Series 1 except: v01, v02
  Potential savings: 6.1 GB if merged

Resolution Options:
[M]erge - Move volumes from Series 2 to Series 1
[D]elete - Remove Series 2 (keeping Series 1)
[S]kip - Leave both unchanged
[W]hitelist - Mark as intentional duplicate
[?] Help - Show detailed help
```

## New Features to Add

### Feature 1: Deep Analysis Action
**Purpose**: Perform detailed integrity check and comparison before making decision

**Deep Analysis Should Show**:
- File integrity (can zip files be opened?)
- Page counts for each volume
- Image quality/resolution metadata
- Compression ratios
- Missing or corrupted files
- Checksum/hashing for exact duplicates
- Metadata completeness

**Usage**:
```
Resolution Options:
... [I]nspect - Deep dive into file details
... [V]erify - Check file integrity and quality

> V

Deep Analysis:
  Checking file integrity...
  Series 1 (Manga/Shounen/Issak):
    ✓ v01.cbz - 285 pages, 45.2 MB, CRC: A3F9B2
    ✓ v02.cbz - 272 pages, 42.8 MB, CRC: C7E5A1
    ✓ v03.cbz - 298 pages, 48.1 MB, CRC: B9D4C3
    ...
    15/15 files OK
  
  Series 2 (Manga/Comedy/Issak Comic):
    ✓ v01.cbz - 285 pages, 44.8 MB, CRC: A3F9B2 (IDENTICAL)
    ✓ v02.cbz - 272 pages, 42.1 MB, CRC: C7E5A1 (IDENTICAL)
    ✗ v03.cbz - CORRUPTED (cannot open)
    ...
    11/12 files OK, 1 corrupted

  Summary: Series 2 has identical files but is incomplete and has corruption
  Recommendation: Delete Series 2, keep Series 1
```

### Feature 2: Enhanced Information Display
**Always show for each duplicate group**:
1. **Basic Info**: Paths, sizes, file counts, date added
2. **Metadata**: MAL IDs, categories, tags, descriptions
3. **File Details**: Volume lists, chapter counts, missing files
4. **Comparison**: Side-by-side differences, potential savings
5. **Quality Metrics**: Average file size, compression, completeness

## Implementation Plan

### Phase 1: Fix MAL ID Detection Bug
- [x] Add debug logging to MALIDDuplicateDetector
- [x] Log each series with its MAL ID during scan
- [x] Log mal_id_map contents before creating groups
- [x] Add diagnostic output showing total series scanned, series with MAL IDs, etc.
- [x] Verify series.mal_id attribute access and type
- [x] Test with known duplicate MAL IDs

### Phase 2: Enhance Information Display
- [x] Create `format_series_details()` function in dedupe_resolver.py
- [x] Display full paths for all series in duplicate group
- [x] Show file listings with sizes and page counts
- [x] Add volume/chapter comparison table
- [x] Show metadata differences (categories, tags, descriptions)
- [x] Calculate and display potential space savings
- [x] Add date added information

### Phase 3: Implement Deep Analysis Action
- [x] Create deep analysis functionality (_deep_inspection method)
- [x] Create integrity verification (_verify_integrity method)
- [x] Implement file integrity checking (zip file validation)
- [x] Add page count extraction and comparison
- [x] Calculate file checksums/hashes for exact duplicate detection
- [x] Generate detailed comparison report
- [x] Add interactive prompt after analysis completes

### Phase 4: Update Resolution Workflow
- [x] Add 'I' (Inspect) and 'V' (Verify) options to resolution prompt
- [x] Integrate deep analysis into main resolution flow
- [x] Update help text to explain new options
- [ ] Add whitelist management with reasons
- [ ] Improve navigation (back/forward between duplicates)

### Phase 5: Testing and Validation
- [x] Test MAL ID detection with known duplicates
- [x] Verify enhanced display shows all required information
- [x] Test deep analysis on various file types
- [x] Test with corrupted files
- [x] Verify whitelist functionality
- [x] Performance test on large libraries

## Files to Modify

1. **dedupe_engine.py** - Fix MAL ID detection, add debug logging
2. **dedupe_resolver.py** - Enhance display, add deep analysis integration
3. **dedupe_actions.py** - Implement deep analysis functionality
4. **cli/dedupe.py** - Update help text, add new action handlers

## Expected Behavior After Fixes

### Before (Buggy):
```
Scanning library... Done
Building duplicate index... Done
Found 3 duplicate groups:

[1/3] ???
Affected Series: Issak
Resolution: [M/D/S] >
```

### After (Fixed):
```
Scanning library... Done
Building duplicate index... Done
[Diagnostic] Scanned 2,450 series, found 847 with MAL IDs
[Diagnostic] Building MAL ID map... found 8 duplicate MAL ID groups

Found 8 duplicate groups:

[1/8] MAL ID Conflict: 12345 (95% confidence)
┌─────────────────────────────────────────────────────────────────────┐
│ Series 1: Manga/Shounen/Issak                                       │
│   Files: 15 volumes (8.2 GB)                                        │
│   Added: 2024-01-15                                                 │
│   Categories: Action, Drama                                         │
│                                                                      │
│ Series 2: Manga/Comedy/Issak Comic                                  │
│   Files: 12 volumes (6.1 GB)                                        │
│   Added: 2024-03-22                                                 │
│   Categories: Comedy, Slice of Life                                 │
│                                                                      │
│ Differences: Series 1 has v13-15, Series 2 missing v01-v02         │
│ Potential savings: 6.1 GB if merged                                 │
└─────────────────────────────────────────────────────────────────────┘

Resolution Options:
[M]erge    - Move volumes from Series 2 to Series 1
[D]elete   - Remove Series 2 (keeping Series 1)
[I]nspect  - Deep dive into file details and quality
[V]erify   - Check file integrity and completeness
[S]kip     - Leave both unchanged
[W]hitelist- Mark as intentional duplicate
[?] Help   - Show detailed help

> I

[Deep Analysis Running...]

Series 1: 15/15 files OK, average 45.2 MB/volume
Series 2: 11/12 files OK, 1 corrupted, average 44.8 MB/volume

Recommendation: Delete Series 2 (incomplete and corrupted)

Proceed with deletion? [y/N] >
```

## Success Criteria

- [ ] MAL ID duplicates are correctly detected and displayed
- [ ] Each duplicate group shows full paths and file information
- [ ] Deep analysis provides integrity checks and detailed comparisons
- [ ] User can make informed decisions based on displayed information
- [ ] Performance remains acceptable (parallel processing maintained)
- [ ] All existing functionality preserved