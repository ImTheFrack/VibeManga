#!/usr/bin/env python3
"""
Test script to verify volume counting with subgroups works correctly.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from vibe_manga.vibe_manga.models import Series, SubGroup, Volume, SeriesMetadata

def test_volume_counting():
    """Test that total_volume_count includes subgroups."""
    print("\n" + "="*70)
    print("TEST: Volume Counting with Subgroups")
    print("="*70)
    
    # Create a mock series similar to One Piece
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
        metadata=SeriesMetadata(mal_id=12345)
    )
    
    # Test total_volume_count property
    root_volumes = len(series.volumes)
    subgroup_volumes = sum(len(sg.volumes) for sg in series.sub_groups)
    total_expected = root_volumes + subgroup_volumes
    
    print(f"\nSeries: {series.name}")
    print(f"  Root volumes: {root_volumes}")
    print(f"  Subgroup volumes: {subgroup_volumes}")
    print(f"  Expected total: {total_expected}")
    print(f"  Actual total_volume_count: {series.total_volume_count}")
    
    if series.total_volume_count == total_expected:
        print("\n[SUCCESS] total_volume_count correctly includes subgroups!")
        return True
    else:
        print(f"\n[FAIL] Expected {total_expected}, got {series.total_volume_count}")
        return False

def test_simple_series():
    """Test a series without subgroups."""
    print("\n" + "="*70)
    print("TEST: Simple Series (No Subgroups)")
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
    
    expected = len(series.volumes)
    actual = series.total_volume_count
    
    print(f"\nSeries: {series.name}")
    print(f"  Root volumes: {len(series.volumes)}")
    print(f"  Expected total: {expected}")
    print(f"  Actual total_volume_count: {actual}")
    
    if actual == expected:
        print("\n[SUCCESS] total_volume_count correct for series without subgroups!")
        return True
    else:
        print(f"\n[FAIL] Expected {expected}, got {actual}")
        return False

def run_all_tests():
    """Run all tests."""
    print("\n" + "#"*70)
    print("# VOLUME COUNTING TEST SUITE")
    print("#"*70)
    
    tests = [
        test_volume_counting,
        test_simple_series,
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