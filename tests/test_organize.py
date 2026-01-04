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

@patch("vibe_manga.vibe_manga.cli.organize.suggest_category")
@patch("vibe_manga.vibe_manga.cli.organize.run_scan_with_progress")
@patch("vibe_manga.vibe_manga.cli.organize.get_library_root")
@patch("vibe_manga.vibe_manga.cli.organize.LibraryIndex")
def test_organize_simulate_filtering(mock_index_cls, mock_get_root, mock_scan, mock_suggest, mock_library):
    """Test that filters correctly select candidates."""
    runner = CliRunner()
    
    # Setup mocks
    mock_scan.return_value = mock_library
    mock_get_root.return_value = Path("/tmp/lib")
    mock_index = MagicMock()
    mock_index_cls.return_value = mock_index
    
    # Mock suggest_category to return valid response (avoid network)
    metadata_mock = MagicMock()
    metadata_mock.genres = ["Action"]
    metadata_mock.demographics = ["Shonen"]
    metadata_mock.release_year = 2020
    metadata_mock.synopsis = "A synopsis."

    mock_suggest.return_value = {
        "consensus": {"final_category": "Manga", "final_sub_category": "General", "reason": "Test", "confidence_score": 1.0},
        "moderation": {"classification": "SAFE"},
        "practical": {}, "creative": {}, "metadata": metadata_mock
    }
    
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


@patch("vibe_manga.vibe_manga.cli.organize.suggest_category")
@patch("vibe_manga.vibe_manga.cli.organize.run_scan_with_progress")
@patch("vibe_manga.vibe_manga.cli.organize.get_library_root")
@patch("vibe_manga.vibe_manga.cli.organize.LibraryIndex")
def test_organize_execution_ai_call(mock_index_cls, mock_get_root, mock_scan, mock_suggest, mock_library):
    """Test that AI is called when target is not specified."""
    runner = CliRunner()
    
    mock_scan.return_value = mock_library
    mock_get_root.return_value = Path("/tmp/lib")
    
    # Mock AI response
    metadata_mock = MagicMock()
    metadata_mock.genres = ["Action"]
    metadata_mock.demographics = ["Shonen"]
    metadata_mock.release_year = 2020
    metadata_mock.synopsis = "A synopsis."

    mock_suggest.return_value = {
        "consensus": {
            "final_category": "Manga",
            "final_sub_category": "Ninja",
            "reason": "It's about ninjas",
            "confidence_score": 0.99
        },
        "moderation": {"classification": "SAFE"},
        "practical": {},
        "creative": {},
        "metadata": metadata_mock
    }
    
    # Run against Naruto (Ninja tag)
    result = runner.invoke(cli, ["organize", "--tag", "Ninja", "--simulate", "--auto"])
    
    assert result.exit_code == 0
    
    # Should call suggest_category
    mock_suggest.assert_called_once()
    
    # Verify destination output (Simulate mode)
    # Should move to Manga/Ninja (from consensus)
    assert "Manga/Ninja" in result.output
    assert "Naruto" in result.output

@patch("vibe_manga.vibe_manga.cli.organize.suggest_category")
@patch("vibe_manga.vibe_manga.cli.organize.run_scan_with_progress")
@patch("vibe_manga.vibe_manga.cli.organize.get_library_root")
@patch("vibe_manga.vibe_manga.cli.organize.LibraryIndex")
def test_organize_execution_direct_target(mock_index_cls, mock_get_root, mock_scan, mock_suggest, mock_library):
    """Test that AI is skipped when explicit target is provided."""
    runner = CliRunner()
    
    mock_scan.return_value = mock_library
    mock_get_root.return_value = Path("/tmp/lib")
    
    # Run against Naruto with explicit target
    result = runner.invoke(cli, ["organize", "--tag", "Ninja", "--target", "Archive/Old", "--simulate", "--auto"])
    
    assert result.exit_code == 0
    
    # Should NOT call suggest_category
    mock_suggest.assert_not_called()
    
    # Verify destination output
    assert "Archive/Old" in result.output
    assert "Naruto" in result.output