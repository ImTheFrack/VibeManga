"""
Tests for organize command logic.
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from click.testing import CliRunner
from vibe_manga.vibe_manga.main import cli
from vibe_manga.vibe_manga.models import Library, Category, Series, SeriesMetadata

@pytest.fixture
def mock_library():
    """Create a mock library with some series."""
    lib = Library(path=Path("."), categories=[])
    
    # Category 1: Manga/Action
    cat1 = Category(name="Manga", path=Path("Manga"), sub_categories=[])
    sub1 = Category(name="Action", path=Path("Manga/Action"), parent=cat1, series=[])
    cat1.sub_categories.append(sub1)
    
    # Series 1: Naruto (Action, Tag: Ninja)
    s1 = Series(name="Naruto", path=Path("Manga/Action/Naruto"))
    s1.metadata = SeriesMetadata(title="Naruto", genres=["Action"], tags=["Ninja"], mal_id=1)
    sub1.series.append(s1)
    
    # Category 2: Manga/Romance
    cat2 = Category(name="Manga", path=Path("Manga"), sub_categories=[])
    sub2 = Category(name="Romance", path=Path("Manga/Romance"), parent=cat2, series=[])
    cat2.sub_categories.append(sub2)
    
    # Series 2: Horimiya (Romance, Tag: School)
    s2 = Series(name="Horimiya", path=Path("Manga/Romance/Horimiya"))
    s2.metadata = SeriesMetadata(title="Horimiya", genres=["Romance"], tags=["School"], mal_id=2)
    sub2.series.append(s2)
    
    lib.categories = [cat1, cat2]
    return lib

@patch("vibe_manga.vibe_manga.cli.organize.run_scan_with_progress")
@patch("vibe_manga.vibe_manga.cli.organize.get_library_root")
@patch("vibe_manga.vibe_manga.cli.organize.LibraryIndex")
def test_organize_simulate_filtering(mock_index_cls, mock_get_root, mock_scan, mock_library):
    """Test that filters correctly select candidates."""
    runner = CliRunner()
    
    # Setup mocks
    mock_scan.return_value = mock_library
    mock_get_root.return_value = Path("/tmp/lib")
    mock_index = MagicMock()
    mock_index_cls.return_value = mock_index
    
    # Mock index search to return everything for query tests or specific items
    # For now we won't test query deeply unless we mock search logic.
    # But filters don't use index.search unless query is provided.
    
    # Test 1: Tag Filter (Include "Ninja") -> Should match Naruto
    result = runner.invoke(cli, ["organize", "--tag", "Ninja", "--simulate", "--auto"])
    assert result.exit_code == 0
    assert "Found 1 candidates" in result.output
    assert "Processing: Naruto" in result.output
    assert "Processing: Horimiya" not in result.output

    # Test 2: Genre Filter (Include "Romance") -> Should match Horimiya
    result = runner.invoke(cli, ["organize", "--genre", "Romance", "--simulate", "--auto"])
    assert result.exit_code == 0
    assert "Found 1 candidates" in result.output
    assert "Processing: Horimiya" in result.output
    
    # Test 3: Exclusion (No "Action") -> Should match Horimiya (since logic is: exclude action, but iterate all? No, candidate finding iterates all)
    result = runner.invoke(cli, ["organize", "--no-genre", "Action", "--simulate", "--auto"])
    assert result.exit_code == 0
    # Should find Horimiya (Naruto excluded)
    assert "Found 1 candidates" in result.output
    assert "Processing: Horimiya" in result.output
    
    # Test 4: Source Filter (Include "Manga/Action")
    # Note: Logic checks check_metadata(series, main_cat, sub_cat)
    # parent_path = f"{main_cat.name}/{sub_cat.name}" -> "Manga/Action"
    result = runner.invoke(cli, ["organize", "--source", "Manga/Action", "--simulate", "--auto"])
    assert result.exit_code == 0
    assert "Found 1 candidates" in result.output
    assert "Processing: Naruto" in result.output

    # Test 5: Source Exclusion (Exclude "Manga")
    result = runner.invoke(cli, ["organize", "--no-source", "Manga", "--simulate", "--auto"])
    assert result.exit_code == 0
    # Both start with Manga, so both excluded.
    assert "No series matched" in result.output
