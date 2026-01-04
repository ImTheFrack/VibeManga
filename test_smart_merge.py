"""
Test script for smart merge renaming functionality.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from vibe_manga.vibe_manga.dedupe_actions import ActionExecutor

def test_generate_filename():
    """Test target filename generation."""
    print("Testing _generate_target_filename...")
    
    executor = ActionExecutor(simulate=True)
    
    # Test cases: (source_filename, target_base, target_format, expected_result)
    test_cases = [
        ("One Piece Definitive Edition v01.cbz", "One Piece", "v{:02d}", "One Piece v01.cbz"),
        ("One Piece Definitive Edition v24.cbz", "One Piece", "v{:02d}", "One Piece v24.cbz"),
        ("OP c001.cbz", "One Piece", "c{:03d}", "One Piece c001.cbz"),
        ("OP c123.cbz", "One Piece", "c{:03d}", "One Piece c123.cbz"),
        ("OnePiece unit0001.cbz", "One Piece", "unit{:04d}", "One Piece unit0001.cbz"),
        ("Naruto v1.cbz", "Naruto", "v{}", "Naruto v1.cbz"),
        ("Naruto v10.cbz", "Naruto", "v{}", "Naruto v10.cbz"),
    ]
    
    passed = 0
    failed = 0
    
    for i, (source_name, target_base, target_format, expected) in enumerate(test_cases):
        source_path = Path(f"/tmp/{source_name}")
        result = executor._generate_target_filename(source_path, target_base, target_format)
        
        print(f"\nTest {i+1}:")
        print(f"  Source: '{source_name}'")
        print(f"  Target base: '{target_base}'")
        print(f"  Target format: '{target_format}'")
        print(f"  Result: '{result}'")
        print(f"  Expected: '{expected}'")
        
        if result == expected:
            print(f"  PASS")
            passed += 1
        else:
            print(f"  FAIL")
            failed += 1
    
    print(f"\n\nResults: {passed} passed, {failed} failed")
    return failed == 0

def test_smart_merge_scenario():
    """Test a complete smart merge scenario."""
    print("\n\nTesting smart merge scenario...")
    
    print("\nScenario: Merge 'One Piece Definitive Edition v01-v24' into 'One Piece'")
    print("Target pattern: 'One Piece vXX' (with leading zeros)")
    print("\nSource files:")
    source_files = [
        "One Piece Definitive Edition v01.cbz",
        "One Piece Definitive Edition v02.cbz", 
        "One Piece Definitive Edition v24.cbz"
    ]
    
    executor = ActionExecutor(simulate=True)
    target_base = "One Piece"
    target_format = "v{:02d}"
    
    print("\nRenamed files:")
    for source_file in source_files:
        source_path = Path(f"/tmp/{source_file}")
        result = executor._generate_target_filename(source_path, target_base, target_format)
        print(f"  {source_file} -> {result}")

if __name__ == "__main__":
    print("=" * 70)
    print("Smart Merge Renaming - Test Suite")
    print("=" * 70)
    
    try:
        success = test_generate_filename()
        test_smart_merge_scenario()
        
        print("\n" + "=" * 70)
        if success:
            print("All tests passed!")
        else:
            print("Some tests failed!")
        print("=" * 70)
        
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
