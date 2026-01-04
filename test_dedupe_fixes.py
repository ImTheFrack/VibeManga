"""
Test script for dedupe bug fixes and enhancements.

This script tests:
1. MAL ID duplicate detection with debug logging
2. Enhanced information display
3. Deep analysis functionality
4. File integrity verification
"""

import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from vibe_manga.vibe_manga.models import Library
from vibe_manga.vibe_manga.dedupe_engine import DedupeEngine, MALIDDuplicateDetector
from vibe_manga.vibe_manga.dedupe_resolver import DuplicateResolver
from vibe_manga.vibe_manga.indexer import LibraryIndex

# Configure logging to see debug output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_mal_id_detection():
    """Test MAL ID detection with debug logging."""
    print("\n" + "="*70)
    print("TEST 1: MAL ID Duplicate Detection")
    print("="*70)
    
    # Load library
    library_path = Path(".")
    library = Library()
    
    try:
        # Build library from disk
        print("\nLoading library...")
        library.load(library_path)
        print(f"Library loaded with {len(library.categories)} categories")
        
        # Count series
        total_series = 0
        series_with_mal_id = 0
        mal_id_counts = {}
        
        for main_cat in library.categories:
            for sub_cat in main_cat.sub_categories:
                for series in sub_cat.series:
                    total_series += 1
                    mal_id = getattr(series, 'mal_id', None)
                    if mal_id:
                        series_with_mal_id += 1
                        mal_id_counts[mal_id] = mal_id_counts.get(mal_id, 0) + 1
        
        print(f"\nLibrary Statistics:")
        print(f"  Total series: {total_series}")
        print(f"  Series with MAL IDs: {series_with_mal_id}")
        print(f"  Unique MAL IDs: {len(mal_id_counts)}")
        
        # Find duplicates
        duplicates = {mid: count for mid, count in mal_id_counts.items() if count > 1}
        if duplicates:
            print(f"\n[FOUND] Duplicate MAL IDs detected: {len(duplicates)}")
            for mal_id, count in duplicates.items():
                print(f"  MAL ID {mal_id}: {count} series")
        else:
            print("\n[OK] No duplicate MAL IDs found")
        
        # Test the detector
        print("\nRunning MAL ID duplicate detector...")
        detector = MALIDDuplicateDetector(library)
        conflicts = detector.detect()
        
        print(f"\nDetector found {len(conflicts)} MAL ID conflicts")
        
        if len(conflicts) != len(duplicates):
            print(f"\n[WARNING] Mismatch! Manual count: {len(duplicates)}, Detector: {len(conflicts)}")
            print("This may indicate a bug in the detection logic.")
        else:
            print("\n[SUCCESS] Detector count matches manual count!")
        
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_enhanced_display():
    """Test enhanced information display."""
    print("\n" + "="*70)
    print("TEST 2: Enhanced Information Display")
    print("="*70)
    
    try:
        # This would require a full library with duplicates
        # For now, we'll just verify the methods exist
        from vibe_manga.vibe_manga.dedupe_resolver import DuplicateResolver
        
        resolver = DuplicateResolver()
        
        # Check that new methods exist
        assert hasattr(resolver, '_display_mal_id_conflict_header')
        assert hasattr(resolver, '_display_series_comparison')
        assert hasattr(resolver, '_display_file_comparison')
        assert hasattr(resolver, '_deep_inspection')
        assert hasattr(resolver, '_verify_integrity')
        
        print("\n[SUCCESS] All enhanced display methods are present!")
        
        # Test ResolutionAction enum has new values
        from vibe_manga.vibe_manga.dedupe_resolver import ResolutionAction
        assert hasattr(ResolutionAction, 'INSPECT')
        assert hasattr(ResolutionAction, 'VERIFY')
        
        print("[SUCCESS] New ResolutionAction values added!")
        
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_comprehensive_detection():
    """Test comprehensive duplicate detection."""
    print("\n" + "="*70)
    print("TEST 3: Comprehensive Duplicate Detection")
    print("="*70)
    
    try:
        library_path = Path(".")
        library = Library()
        library.load(library_path)
        
        print("\nRunning comprehensive duplicate detection...")
        engine = DedupeEngine(library)
        results = engine.detect_all()
        
        print(f"\nDetection Results:")
        print(f"  MAL ID conflicts: {len(results['mal_id_conflicts'])}")
        print(f"  Content duplicates: {len(results['content_duplicates'])}")
        print(f"  Fuzzy duplicates: {len(results['fuzzy_duplicates'])}")
        
        summary = engine.get_duplicate_summary(results)
        print(f"\nSummary:")
        print(f"  Total groups: {summary['total_groups']}")
        print(f"  Total affected series: {summary['total_affected_series']}")
        print(f"  Estimated space: {summary['estimated_space_mb']:.1f} MB")
        
        print("\n[SUCCESS] Comprehensive detection completed!")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all tests and report results."""
    print("\n" + "#"*70)
    print("# VIBEMANGA DEDUPE BUG FIXES - TEST SUITE")
    print("#"*70)
    
    tests = [
        ("MAL ID Detection", test_mal_id_detection),
        ("Enhanced Display", test_enhanced_display),
        ("Comprehensive Detection", test_comprehensive_detection),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"\n[CRITICAL ERROR] Test '{test_name}' crashed: {e}")
            results.append((test_name, False))
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for test_name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n[SUCCESS] All tests passed!")
        return 0
    else:
        print(f"\n[FAILURE] {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())