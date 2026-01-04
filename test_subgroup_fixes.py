#!/usr/bin/env python3
"""
Test script to verify subgroup volume fixes work correctly.
"""

import sys
from pathlib import Path
from unittest.mock import Mock

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from vibe_manga.vibe_manga.models import Series, SubGroup, Volume, SeriesMetadata
from vibe_manga.vibe_manga.dedupe_resolver import DuplicateResolver

def test_get_all_volumes():
    """Test that _get_all_volumes includes subgroups."""
    print("\n" + "="*70)
    print("TEST: Get All Volumes (Including Subgroups)")
    print("="*70)
    
    # Create a series with subgroups (like One Piece)
    series = Series(
        name="One Piece",
        path=Path("/Manga/Shounen/One Piece"),
        volumes=[
            Volume(path=Path("/Manga/Shounen/One Piece/v100.cbz"), name="v100.cbz", size_bytes=1000000),
            Volume(path=Path("/Manga/Shounen/One Piece/v101.cbz"), name="v101.cbz", size_bytes=1000000),
            Volume(path=Path("/Manga/Shounen/One Piece/v102.cbz"), name="v102.cbz", size_bytes=1000000),
        ],
        sub_groups=[
            SubGroup(
                name="v01-v50",
                path=Path("/Manga/Shounen/One Piece/v01-v50"),
                volumes=[
                    Volume(path=Path("/Manga/Shounen/One Piece/v01-v50/v01.cbz"), name="v01.cbz", size_bytes=1000000),
                    Volume(path=Path("/Manga/Shounen/One Piece/v01-v50/v02.cbz"), name="v02.cbz", size_bytes=1000000),
                ]
            ),
            SubGroup(
                name="v51-v99",
                path=Path("/Manga/Shounen/One Piece/v51-v99"),
                volumes=[
                    Volume(path=Path("/Manga/Shounen/One Piece/v51-v99/v51.cbz"), name="v51.cbz", size_bytes=1000000),
                    Volume(path=Path("/Manga/Shounen/One Piece/v51-v99/v52.cbz"), name="v52.cbz", size_bytes=1000000),
                ]
            ),
        ],
        metadata=SeriesMetadata(mal_id=13, title="One Piece")
    )
    
    # Test the helper method
    resolver = DuplicateResolver()
    all_volumes = resolver._get_all_volumes(series)
    
    root_count = len(series.volumes)
    subgroup_count = sum(len(sg.volumes) for sg in series.sub_groups)
    expected_total = root_count + subgroup_count
    actual_total = len(all_volumes)
    
    print(f"\nSeries: {series.name}")
    print(f"  Root volumes: {root_count}")
    print(f"  Subgroup volumes: {subgroup_count}")
    print(f"  Expected total: {expected_total}")
    print(f"  Actual from _get_all_volumes: {actual_total}")
    
    # Check that all volumes are included
    root_names = {v.name for v in series.volumes}
    subgroup_names = {v.name for sg in series.sub_groups for v in sg.volumes}
    all_names = {v.name for v in all_volumes}
    
    print(f"\n  Root volume names: {root_names}")
    print(f"  Subgroup volume names: {subgroup_names}")
    print(f"  All volume names: {all_names}")
    
    if actual_total == expected_total and all_names == root_names | subgroup_names:
        print("\n[SUCCESS] _get_all_volumes correctly includes subgroups!")
        return True
    else:
        print(f"\n[FAIL] Expected {expected_total} volumes, got {actual_total}")
        return False

def test_get_mal_id():
    """Test that _get_mal_id correctly accesses metadata.mal_id."""
    print("\n" + "="*70)
    print("TEST: Get MAL ID from Metadata")
    print("="*70)
    
    # Create series with MAL ID in metadata
    series = Series(
        name="Test Manga",
        path=Path("/Manga/Shounen/Test"),
        volumes=[],
        sub_groups=[],
        metadata=SeriesMetadata(mal_id=12345, title="Test Manga")
    )
    
    resolver = DuplicateResolver()
    mal_id = resolver._get_mal_id(series)
    
    print(f"\nSeries: {series.name}")
    print(f"  MAL ID in metadata: {series.metadata.mal_id}")
    print(f"  MAL ID from _get_mal_id: {mal_id}")
    
    if mal_id == 12345:
        print("\n[SUCCESS] _get_mal_id correctly retrieves MAL ID from metadata!")
        return True
    else:
        print(f"\n[FAIL] Expected 12345, got {mal_id}")
        return False

def test_series_without_subgroups():
    """Test that _get_all_volumes works for series without subgroups."""
    print("\n" + "="*70)
    print("TEST: Series Without Subgroups")
    print("="*70)
    
    series = Series(
        name="Simple Manga",
        path=Path("/Manga/Shounen/Simple"),
        volumes=[
            Volume(path=Path("/Manga/Shounen/Simple/v01.cbz"), name="v01.cbz", size_bytes=1000000),
            Volume(path=Path("/Manga/Shounen/Simple/v02.cbz"), name="v02.cbz", size_bytes=1000000),
            Volume(path=Path("/Manga/Shounen/Simple/v03.cbz"), name="v03.cbz", size_bytes=1000000),
        ],
        sub_groups=[],
        metadata=SeriesMetadata(mal_id=67890)
    )
    
    resolver = DuplicateResolver()
    all_volumes = resolver._get_all_volumes(series)
    
    expected = len(series.volumes)
    actual = len(all_volumes)
    
    print(f"\nSeries: {series.name}")
    print(f"  Root volumes: {len(series.volumes)}")
    print(f"  Expected total: {expected}")
    print(f"  Actual from _get_all_volumes: {actual}")
    
    if actual == expected:
        print("\n[SUCCESS] _get_all_volumes works correctly for series without subgroups!")
        return True
    else:
        print(f"\n[FAIL] Expected {expected}, got {actual}")
        return False

def run_all_tests():
    """Run all tests."""
    print("\n" + "#"*70)
    print("# SUBGROUP VOLUME FIXES TEST SUITE")
    print("#"*70)
    
    tests = [
        test_get_all_volumes,
        test_get_mal_id,
        test_series_without_subgroups,
    ]
    
    results = []
    for test_func in tests:
        try:
            success = test_func()
            results.append((test_func.__name__, success))
        except Exception as e:
            print(f"\n[ERROR] in {test_func.__name__}: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_func.__name__, False))
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for test_name, success in results:
        status = "[PASS]" if success else "[FAIL]"
        print(f"{status}: {test_name}")
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\nAll tests passed!")
        return 0
    else:
        print(f"\n{total - passed} test(s) failed")
        return 1

if __name__ == "__main__":
    sys.exit(run_all_tests())