#!/usr/bin/env python3
"""
Test script for the new dedupe functionality.
Runs basic tests to ensure the modules load and work correctly.
"""

import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Add the vibe_manga package to path
vibe_manga_path = project_root / "vibe_manga"
sys.path.insert(0, str(vibe_manga_path))

def test_imports():
    """Test that all new modules can be imported."""
    print("Testing imports...")
    
    try:
        from vibe_manga.dedupe_engine import DedupeEngine, MALIDDuplicate, ContentDuplicate, DuplicateGroup
        print("[OK] dedupe_engine imports successful")
    except Exception as e:
        print(f"[FAIL] dedupe_engine import failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    try:
        from vibe_manga.dedupe_resolver import DuplicateResolver, ResolutionPlan, ResolutionAction
        print("[OK] dedupe_resolver imports successful")
    except Exception as e:
        print(f"[FAIL] dedupe_resolver import failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    try:
        from vibe_manga.dedupe_actions import ActionExecutor, ActionResult
        print("[OK] dedupe_actions imports successful")
    except Exception as e:
        print(f"[FAIL] dedupe_actions import failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    try:
        from vibe_manga.cli.dedupe import dedupe
        print("[OK] cli.dedupe import successful")
    except Exception as e:
        print(f"[FAIL] cli.dedupe import failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

def test_dataclasses():
    """Test that dataclasses can be instantiated."""
    print("\nTesting dataclass instantiation...")
    
    try:
        from vibe_manga.dedupe_engine import DuplicateGroup, MALIDDuplicate, ContentDuplicate
        from vibe_manga.models import Series, SeriesMetadata, Volume
        from pathlib import Path
        
        # Create a minimal series for testing
        metadata = SeriesMetadata(title="Test", mal_id=12345)
        series = Series(
            name="Test Series",
            path=Path("/fake/path"),
            metadata=metadata
        )
        
        # Test MALIDDuplicate
        mal_dup = MALIDDuplicate(mal_id=12345, series=[series])
        print(f"[OK] MALIDDuplicate created: {mal_dup.mal_id}")
        
        # Test ContentDuplicate
        vol = Volume(path=Path("/fake/vol.cbz"), name="v01.cbz", size_bytes=1024)
        content_dup = ContentDuplicate(file_hash="abc123", file_size=1024, page_count=None, volumes=[vol])
        print(f"[OK] ContentDuplicate created: {content_dup.file_hash}")
        
        # Test DuplicateGroup
        group = DuplicateGroup(group_id="test_1", duplicate_type="test", confidence=0.95, items=[series])
        print(f"[OK] DuplicateGroup created: {group.group_id}")
        
        return True
    except Exception as e:
        print(f"[FAIL] Dataclass test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_engine_initialization():
    """Test that DedupeEngine can be initialized."""
    print("\nTesting DedupeEngine initialization...")
    
    try:
        from vibe_manga.dedupe_engine import DedupeEngine
        from vibe_manga.models import Library
        from pathlib import Path
        
        # Create minimal library
        library = Library(path=Path("/fake/library"))
        
        # Initialize engine
        engine = DedupeEngine(library, use_hashing=False)
        print("[OK] DedupeEngine initialized successfully")
        
        return True
    except Exception as e:
        print(f"[FAIL] Engine initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_resolver_initialization():
    """Test that DuplicateResolver can be initialized."""
    print("\nTesting DuplicateResolver initialization...")
    
    try:
        from vibe_manga.dedupe_resolver import DuplicateResolver
        
        resolver = DuplicateResolver()
        print("[OK] DuplicateResolver initialized successfully")
        
        return True
    except Exception as e:
        print(f"[FAIL] Resolver initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing VibeManga Dedupe Refactoring")
    print("=" * 60)
    
    tests = [
        test_imports,
        test_dataclasses,
        test_engine_initialization,
        test_resolver_initialization,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"[FAIL] Test {test.__name__} crashed: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)
    
    if passed == total:
        print("\n[OK] All tests passed! The dedupe refactoring is ready.")
        print("\nYou can now run:")
        print("  python -m vibe_manga.run dedupe --help")
        print("\nExample usage:")
        print("  python -m vibe_manga.run dedupe                    # Interactive mode")
        print("  python -m vibe_manga.run dedupe --mode mal-id     # Only MAL ID conflicts")
        print("  python -m vibe_manga.run dedupe --simulate        # Preview only")
        print("  python -m vibe_manga.run dedupe --auto            # Auto-resolve simple cases")
        return 0
    else:
        print(f"\n[FAIL] {total - passed} test(s) failed. Please check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())