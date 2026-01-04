#!/usr/bin/env python3
"""
Test script to verify --mode flag only runs selected detection modes.
"""

import sys
from pathlib import Path
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from vibe_manga.vibe_manga.dedupe_engine import DedupeEngine, MALIDDuplicateDetector, ContentDuplicateDetector, FuzzyDuplicateDetector
from vibe_manga.vibe_manga.models import Library
from unittest.mock import Mock, patch

def test_detect_by_mode():
    """Test that detect_by_mode only runs the selected detection."""
    print("\n" + "="*70)
    print("TEST: Mode Selection (detect_by_mode)")
    print("="*70)
    
    # Create mock library
    mock_library = Mock(spec=Library)
    mock_library.categories = []
    
    # Create engine
    engine = DedupeEngine(mock_library, use_hashing=False)
    
    # Mock the individual detectors
    with patch.object(engine.mal_detector, 'detect', return_value=['mal_conflict_1', 'mal_conflict_2']) as mock_mal, \
         patch.object(engine.content_detector, 'detect', return_value=['content_dup_1']) as mock_content, \
         patch.object(engine.fuzzy_detector, 'detect', return_value=['fuzzy_match_1']) as mock_fuzzy:
        
        print("\n1. Testing mode='mal-id'...")
        results = engine.detect_by_mode('mal-id')
        
        # Verify only MAL detector was called
        assert mock_mal.called, "MAL detector should be called"
        assert not mock_content.called, "Content detector should NOT be called"
        assert not mock_fuzzy.called, "Fuzzy detector should NOT be called"
        
        # Verify results
        assert len(results['mal_id_conflicts']) == 2, f"Expected 2 MAL conflicts, got {len(results['mal_id_conflicts'])}"
        assert len(results['content_duplicates']) == 0, f"Expected 0 content dups, got {len(results['content_duplicates'])}"
        assert len(results['fuzzy_duplicates']) == 0, f"Expected 0 fuzzy matches, got {len(results['fuzzy_duplicates'])}"
        
        print("   [OK] Only MAL ID detection ran")
        print(f"   [OK] Found {len(results['mal_id_conflicts'])} MAL ID conflicts")
        
        # Reset mocks
        mock_mal.reset_mock()
        mock_content.reset_mock()
        mock_fuzzy.reset_mock()
        
        print("\n2. Testing mode='content'...")
        results = engine.detect_by_mode('content')
        
        # Verify only content detector was called
        assert not mock_mal.called, "MAL detector should NOT be called"
        assert mock_content.called, "Content detector should be called"
        assert not mock_fuzzy.called, "Fuzzy detector should NOT be called"
        
        # Verify results
        assert len(results['mal_id_conflicts']) == 0, f"Expected 0 MAL conflicts, got {len(results['mal_id_conflicts'])}"
        assert len(results['content_duplicates']) == 1, f"Expected 1 content dup, got {len(results['content_duplicates'])}"
        assert len(results['fuzzy_duplicates']) == 0, f"Expected 0 fuzzy matches, got {len(results['fuzzy_duplicates'])}"
        
        print("   [OK] Only content detection ran")
        print(f"   [OK] Found {len(results['content_duplicates'])} content duplicate")
        
        # Reset mocks
        mock_mal.reset_mock()
        mock_content.reset_mock()
        mock_fuzzy.reset_mock()
        
        print("\n3. Testing mode='fuzzy'...")
        results = engine.detect_by_mode('fuzzy')
        
        # Verify only fuzzy detector was called
        assert not mock_mal.called, "MAL detector should NOT be called"
        assert not mock_content.called, "Content detector should NOT be called"
        assert mock_fuzzy.called, "Fuzzy detector should be called"
        
        # Verify results
        assert len(results['mal_id_conflicts']) == 0, f"Expected 0 MAL conflicts, got {len(results['mal_id_conflicts'])}"
        assert len(results['content_duplicates']) == 0, f"Expected 0 content dups, got {len(results['content_duplicates'])}"
        assert len(results['fuzzy_duplicates']) == 1, f"Expected 1 fuzzy match, got {len(results['fuzzy_duplicates'])}"
        
        print("   [OK] Only fuzzy detection ran")
        print(f"   [OK] Found {len(results['fuzzy_duplicates'])} fuzzy match")
        
        # Reset mocks
        mock_mal.reset_mock()
        mock_content.reset_mock()
        mock_fuzzy.reset_mock()
        
        print("\n4. Testing mode='all'...")
        with patch.object(engine, 'detect_all', return_value={
            'mal_id_conflicts': ['mal1', 'mal2'],
            'content_duplicates': ['content1'],
            'fuzzy_duplicates': ['fuzzy1', 'fuzzy2']
        }) as mock_detect_all:
            results = engine.detect_by_mode('all')
            
            # Verify detect_all was called
            assert mock_detect_all.called, "detect_all should be called for mode='all'"
            assert not mock_mal.called, "Individual MAL detector should NOT be called"
            assert not mock_content.called, "Individual content detector should NOT be called"
            assert not mock_fuzzy.called, "Individual fuzzy detector should NOT be called"
            
            # Verify all results are present
            assert len(results['mal_id_conflicts']) == 2, f"Expected 2 MAL conflicts, got {len(results['mal_id_conflicts'])}"
            assert len(results['content_duplicates']) == 1, f"Expected 1 content dup, got {len(results['content_duplicates'])}"
            assert len(results['fuzzy_duplicates']) == 2, f"Expected 2 fuzzy matches, got {len(results['fuzzy_duplicates'])}"
            
            print("   [OK] detect_all() was called")
            print(f"   [OK] Found {len(results['mal_id_conflicts'])} MAL ID conflicts")
            print(f"   [OK] Found {len(results['content_duplicates'])} content duplicates")
            print(f"   [OK] Found {len(results['fuzzy_duplicates'])} fuzzy matches")
    
    print("\n" + "="*70)
    print("All mode selection tests passed!")
    print("="*70)
    
    return True

def test_performance_difference():
    """Test that selective mode is faster than running all modes."""
    print("\n" + "="*70)
    print("TEST: Performance Difference")
    print("="*70)
    
    # Create mock library
    mock_library = Mock(spec=Library)
    mock_library.categories = []
    
    # Create engine
    engine = DedupeEngine(mock_library, use_hashing=False)
    
    # Mock detectors with delays to simulate real work
    def slow_detection():
        time.sleep(0.1)  # Simulate 100ms of work
        return ['result1', 'result2']
    
    with patch.object(engine.mal_detector, 'detect', side_effect=slow_detection) as mock_mal, \
         patch.object(engine.content_detector, 'detect', side_effect=slow_detection) as mock_content, \
         patch.object(engine.fuzzy_detector, 'detect', side_effect=slow_detection) as mock_fuzzy:
        
        # Time running all modes
        start = time.time()
        engine.detect_all()
        all_modes_time = time.time() - start
        
        # Time running only MAL ID mode
        start = time.time()
        engine.detect_by_mode('mal-id')
        mal_only_time = time.time() - start
        
        print(f"\nTime for all modes: {all_modes_time:.3f}s")
        print(f"Time for MAL-ID only: {mal_only_time:.3f}s")
        print(f"Speedup: {all_modes_time / mal_only_time:.1f}x faster")
        
        # MAL-only should be significantly faster (close to 3x in this case)
        assert mal_only_time < all_modes_time * 0.5, "MAL-only should be at least 2x faster than all modes"
        
        print("\n[OK] Selective mode detection is significantly faster")
    
    return True

def run_all_tests():
    """Run all tests."""
    print("\n" + "#"*70)
    print("# MODE SELECTION TEST SUITE")
    print("#"*70)
    
    tests = [
        test_detect_by_mode,
        test_performance_difference,
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