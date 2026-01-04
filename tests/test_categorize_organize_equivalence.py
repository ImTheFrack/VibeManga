"""
Tests to verify that 'categorize' command correctly aliases to 'organize'.

Since 'categorize' is now a wrapper around 'organize', these tests ensure
that invoking 'categorize' triggers the expected 'organize' logic with correct defaults.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from click.testing import CliRunner
from vibe_manga.vibe_manga.main import cli
from vibe_manga.vibe_manga.models import Library, Category, Series, SeriesMetadata

@pytest.fixture
def mock_uncategorized_library():
    """Create a mock library with series in Uncategorized."""
    lib = Library(path=Path("/tmp/lib"), categories=[])
    
    uncategorized = Category(name="Uncategorized", path=Path("Uncategorized"), sub_categories=[])
    uncategorized_sub = Category(name="Imported", path=Path("Uncategorized/Imported"), parent=uncategorized, series=[])
    uncategorized.sub_categories.append(uncategorized_sub)
    
    s1 = Series(name="Series One", path=Path("Uncategorized/Imported/Series One"))
    s1.metadata = SeriesMetadata(title="Series One", genres=["Action"], tags=["Shonen"], mal_id=1)
    uncategorized_sub.series.append(s1)
    
    lib.categories = [uncategorized]
    return lib

@pytest.fixture
def mock_ai_response():
    """Standard AI response."""
    metadata_mock = MagicMock()
    metadata_mock.synopsis = "A test series synopsis"
    metadata_mock.genres = ["Action"]
    
    return {
        "consensus": {
            "final_category": "Manga",
            "final_sub_category": "Action",
            "reason": "Contains action themes",
            "confidence_score": 0.95
        },
        "moderation": {"classification": "SAFE", "reason": "Safe content"},
        "practical": {"category": "Manga/Action", "reason": "Action genre"},
        "creative": {"category": "Manga/Action", "reason": "Action themes"},
        "metadata": metadata_mock
    }

class TestCategorizeAlias:
    """Test suite for verifying categorize alias behavior."""
    
    @patch("vibe_manga.vibe_manga.cli.organize.suggest_category")
    @patch("vibe_manga.vibe_manga.cli.organize.run_scan_with_progress")
    @patch("vibe_manga.vibe_manga.cli.organize.get_library_root")
    def test_categorize_invokes_organize_logic(
        self, 
        mock_root, mock_scan, mock_suggest,
        mock_uncategorized_library, mock_ai_response
    ):
        """
        Test that running 'categorize' invokes the organize pipeline.
        """
        # Setup mocks
        mock_root.return_value = Path("/tmp/lib")
        mock_scan.return_value = mock_uncategorized_library
        mock_suggest.return_value = mock_ai_response
        
        runner = CliRunner()
        
        # Run categorize
        result = runner.invoke(cli, [
            "categorize", 
            "--simulate", 
            "--auto",
            "--no-cache"
        ])
        
        assert result.exit_code == 0
        assert "categorize' is now an alias" in result.output
        
        # Verify organize components were called
        mock_scan.assert_called_once()
        mock_suggest.assert_called_once()
        
        # Verify args passed to suggest_category (organize logic)
        # Series One should be processed
        series_arg = mock_suggest.call_args[0][0]
        assert series_arg.name == "Series One"
        
        # Check defaults: categorize should default to Uncategorized source
        # We can't easily check the click context params here, but we can verify behavior.
        # If it processed "Series One" (which is in Uncategorized), it's working.

    @patch("vibe_manga.vibe_manga.cli.organize.suggest_category")
    @patch("vibe_manga.vibe_manga.cli.organize.run_scan_with_progress")
    @patch("vibe_manga.vibe_manga.cli.organize.get_library_root")
    def test_categorize_passes_query(
        self,
        mock_root, mock_scan, mock_suggest,
        mock_uncategorized_library, mock_ai_response
    ):
        """Test that query argument is passed through."""
        mock_root.return_value = Path("/tmp/lib")
        mock_scan.return_value = mock_uncategorized_library
        mock_suggest.return_value = mock_ai_response
        
        runner = CliRunner()
        result = runner.invoke(cli, ["categorize", "Series One", "--simulate", "--auto"])
        
        assert result.exit_code == 0
        mock_suggest.assert_called()
        assert mock_suggest.call_args[0][0].name == "Series One"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])