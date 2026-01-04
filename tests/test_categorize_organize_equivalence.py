"""
Tests to verify equivalence between 'categorize' and 'organize --source "Uncategorized"'.

According to ORGANIZEPLAN.md:
"Running organize --source "Uncategorized" is functionally identical to running categorize"
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from click.testing import CliRunner
from vibe_manga.vibe_manga.main import cli
from vibe_manga.vibe_manga.models import Library, Category, Series, SeriesMetadata


@pytest.fixture
def mock_uncategorized_library():
    """Create a mock library with series in Uncategorized and other categories."""
    lib = Library(path=Path("/tmp/lib"), categories=[])
    
    # Uncategorized category with 2 series
    uncategorized = Category(name="Uncategorized", path=Path("Uncategorized"), sub_categories=[])
    uncategorized_sub = Category(name="Imported", path=Path("Uncategorized/Imported"), parent=uncategorized, series=[])
    uncategorized.sub_categories.append(uncategorized_sub)
    
    s1 = Series(name="Series One", path=Path("Uncategorized/Imported/Series One"))
    s1.metadata = SeriesMetadata(title="Series One", genres=["Action"], tags=["Shonen"], mal_id=1)
    uncategorized_sub.series.append(s1)
    
    s2 = Series(name="Series Two", path=Path("Uncategorized/Imported/Series Two"))
    s2.metadata = SeriesMetadata(title="Series Two", genres=["Romance"], tags=["School"], mal_id=2)
    uncategorized_sub.series.append(s2)
    
    # Manga category with 1 series (should NOT be processed)
    manga = Category(name="Manga", path=Path("Manga"), sub_categories=[])
    manga_sub = Category(name="Action", path=Path("Manga/Action"), parent=manga, series=[])
    manga.sub_categories.append(manga_sub)
    
    s3 = Series(name="Series Three", path=Path("Manga/Action/Series Three"))
    s3.metadata = SeriesMetadata(title="Series Three", genres=["Action"], tags=["Ninja"], mal_id=3)
    manga_sub.series.append(s3)
    
    lib.categories = [uncategorized, manga]
    return lib


@pytest.fixture
def mock_ai_response():
    """Standard AI response for successful categorization."""
    metadata_mock = MagicMock()
    metadata_mock.synopsis = "A test series synopsis"
    metadata_mock.genres = ["Action"]
    metadata_mock.demographics = ["Shonen"]
    metadata_mock.release_year = 2020
    
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


class TestCategorizeOrganizeEquivalence:
    """Test suite for verifying categorize vs organize --source equivalence."""
    
    @patch("vibe_manga.vibe_manga.cli.organize.suggest_category")
    @patch("vibe_manga.vibe_manga.cli.categorize.suggest_category")
    @patch("vibe_manga.vibe_manga.cli.organize.run_scan_with_progress")
    @patch("vibe_manga.vibe_manga.cli.categorize.run_scan_with_progress")
    @patch("vibe_manga.vibe_manga.cli.organize.get_library_root")
    @patch("vibe_manga.vibe_manga.cli.categorize.get_library_root")
    def test_both_commands_select_same_series(
        self, 
        mock_categorize_root, mock_organize_root,
        mock_categorize_scan, mock_organize_scan,
        mock_categorize_suggest, mock_organize_suggest,
        mock_uncategorized_library, mock_ai_response
    ):
        """
        Test that both commands select the same series from Uncategorized.
        
        This is the core equivalence test - both commands should identify
        the same candidate series when run with the same library state.
        """
        # Setup mocks
        mock_categorize_root.return_value = Path("/tmp/lib")
        mock_organize_root.return_value = Path("/tmp/lib")
        mock_categorize_scan.return_value = mock_uncategorized_library
        mock_organize_scan.return_value = mock_uncategorized_library
        
        # Track which series each command processes
        categorize_processed = []
        organize_processed = []
        
        def categorize_suggest_side_effect(series, *args, **kwargs):
            categorize_processed.append(series.name)
            return mock_ai_response
        
        def organize_suggest_side_effect(series, *args, **kwargs):
            organize_processed.append(series.name)
            return mock_ai_response
        
        mock_categorize_suggest.side_effect = categorize_suggest_side_effect
        mock_organize_suggest.side_effect = organize_suggest_side_effect
        
        runner = CliRunner()
        
        # Run categorize in simulate+auto mode
        result_categorize = runner.invoke(cli, [
            "categorize", 
            "--simulate", 
            "--auto",
            "--no-cache"
        ])
        
        # Run organize with --source "Uncategorized" in simulate+auto mode
        result_organize = runner.invoke(cli, [
            "organize",
            "--source", "Uncategorized",
            "--simulate",
            "--auto",
            "--no-cache"
        ])
        
        # Both should succeed
        assert result_categorize.exit_code == 0, f"categorize failed: {result_categorize.output}"
        assert result_organize.exit_code == 0, f"organize failed: {result_organize.output}"
        
        # Both should find and process the same series
        assert len(categorize_processed) == 2, f"categorize processed {len(categorize_processed)} series, expected 2"
        assert len(organize_processed) == 2, f"organize processed {len(organize_processed)} series, expected 2"
        assert set(categorize_processed) == set(organize_processed), \
            f"Commands processed different series: categorize={categorize_processed}, organize={organize_processed}"
        
        # Verify the series names
        expected_series = {"Series One", "Series Two"}
        assert set(categorize_processed) == expected_series
        
        print("✓ Both commands selected the same series from Uncategorized")
    
    @patch("vibe_manga.vibe_manga.cli.organize.suggest_category")
    @patch("vibe_manga.vibe_manga.cli.categorize.suggest_category")
    @patch("vibe_manga.vibe_manga.cli.organize.run_scan_with_progress")
    @patch("vibe_manga.vibe_manga.cli.categorize.run_scan_with_progress")
    @patch("vibe_manga.vibe_manga.cli.organize.get_library_root")
    @patch("vibe_manga.vibe_manga.cli.categorize.get_library_root")
    def test_both_commands_use_same_ai_parameters(
        self,
        mock_categorize_root, mock_organize_root,
        mock_categorize_scan, mock_organize_scan,
        mock_categorize_suggest, mock_organize_suggest,
        mock_uncategorized_library, mock_ai_response
    ):
        """
        Test that both commands call suggest_category with equivalent parameters.
        
        Both should:
        - Pass the series object
        - Pass the library object
        - Pass user_feedback=None (in auto mode)
        - Not pass custom_categories (when not using --newroot)
        - Not pass restrict_to_main (when target is not specified)
        """
        mock_categorize_root.return_value = Path("/tmp/lib")
        mock_organize_root.return_value = Path("/tmp/lib")
        mock_categorize_scan.return_value = mock_uncategorized_library
        mock_organize_scan.return_value = mock_uncategorized_library
        mock_categorize_suggest.return_value = mock_ai_response
        mock_organize_suggest.return_value = mock_ai_response
        
        runner = CliRunner()
        
        # Run both commands
        runner.invoke(cli, ["categorize", "--simulate", "--auto", "--no-cache"])
        runner.invoke(cli, ["organize", "--source", "Uncategorized", "--simulate", "--auto", "--no-cache"])
        
        # Check that suggest_category was called
        assert mock_categorize_suggest.called, "categorize did not call suggest_category"
        assert mock_organize_suggest.called, "organize did not call suggest_category"
        
        # Get the call arguments
        categorize_call = mock_categorize_suggest.call_args
        organize_call = mock_organize_suggest.call_args
        
        # Both should pass series and library as first two positional args
        assert categorize_call.args[0].name in ["Series One", "Series Two"]
        assert organize_call.args[0].name in ["Series One", "Series Two"]
        assert categorize_call.args[1] == mock_uncategorized_library
        assert organize_call.args[1] == mock_uncategorized_library
        
        # Both should have user_feedback=None in kwargs (auto mode)
        assert categorize_call.kwargs.get("user_feedback") is None
        assert organize_call.kwargs.get("user_feedback") is None
        
        # Neither should have custom_categories (no --newroot)
        assert categorize_call.kwargs.get("custom_categories") is None
        assert organize_call.kwargs.get("custom_categories") is None
        
        # Neither should have restrict_to_main (no --target)
        assert categorize_call.kwargs.get("restrict_to_main") is None
        assert organize_call.kwargs.get("restrict_to_main") is None
        
        print("✓ Both commands used equivalent AI parameters")
    
    @patch("vibe_manga.vibe_manga.cli.organize.suggest_category")
    @patch("vibe_manga.vibe_manga.cli.categorize.suggest_category")
    @patch("vibe_manga.vibe_manga.cli.organize.run_scan_with_progress")
    @patch("vibe_manga.vibe_manga.cli.categorize.run_scan_with_progress")
    @patch("vibe_manga.vibe_manga.cli.organize.get_library_root")
    @patch("vibe_manga.vibe_manga.cli.categorize.get_library_root")
    def test_both_commands_respect_query_filter(
        self,
        mock_categorize_root, mock_organize_root,
        mock_categorize_scan, mock_organize_scan,
        mock_categorize_suggest, mock_organize_suggest,
        mock_uncategorized_library, mock_ai_response
    ):
        """
        Test that both commands respect the query argument equally.
        
        When a query is provided, both should only process matching series.
        """
        mock_categorize_root.return_value = Path("/tmp/lib")
        mock_organize_root.return_value = Path("/tmp/lib")
        mock_categorize_scan.return_value = mock_uncategorized_library
        mock_organize_scan.return_value = mock_uncategorized_library
        mock_categorize_suggest.return_value = mock_ai_response
        mock_organize_suggest.return_value = mock_ai_response
        
        runner = CliRunner()
        
        # Run with query "Series One"
        result_categorize = runner.invoke(cli, [
            "categorize", 
            "Series One",
            "--simulate", 
            "--auto",
            "--no-cache"
        ])
        
        result_organize = runner.invoke(cli, [
            "organize",
            "Series One",
            "--source", "Uncategorized",
            "--simulate",
            "--auto",
            "--no-cache"
        ])
        
        assert result_categorize.exit_code == 0
        assert result_organize.exit_code == 0
        
        # Both should only process "Series One"
        assert mock_categorize_suggest.call_count == 1
        assert mock_organize_suggest.call_count == 1
        
        categorize_series = mock_categorize_suggest.call_args.args[0]
        organize_series = mock_organize_suggest.call_args.args[0]
        
        assert categorize_series.name == "Series One"
        assert organize_series.name == "Series One"
        
        print("✓ Both commands respect query filter equally")
    
    @patch("vibe_manga.vibe_manga.cli.organize.suggest_category")
    @patch("vibe_manga.vibe_manga.cli.categorize.suggest_category")
    @patch("vibe_manga.vibe_manga.cli.organize.run_scan_with_progress")
    @patch("vibe_manga.vibe_manga.cli.categorize.run_scan_with_progress")
    @patch("vibe_manga.vibe_manga.cli.organize.get_library_root")
    @patch("vibe_manga.vibe_manga.cli.categorize.get_library_root")
    def test_organize_with_source_uncategorized_excludes_non_uncategorized(
        self,
        mock_categorize_root, mock_organize_root,
        mock_categorize_scan, mock_organize_scan,
        mock_categorize_suggest, mock_organize_suggest,
        mock_uncategorized_library, mock_ai_response
    ):
        """
        Test that organize --source "Uncategorized" only processes Uncategorized series.
        
        This verifies that organize with --source filter behaves like categorize
        and doesn't process series from other categories.
        """
        mock_categorize_root.return_value = Path("/tmp/lib")
        mock_organize_root.return_value = Path("/tmp/lib")
        mock_categorize_scan.return_value = mock_uncategorized_library
        mock_organize_scan.return_value = mock_uncategorized_library
        mock_categorize_suggest.return_value = mock_ai_response
        mock_organize_suggest.return_value = mock_ai_response
        
        runner = CliRunner()
        
        # Run organize with --source "Uncategorized"
        result = runner.invoke(cli, [
            "organize",
            "--source", "Uncategorized",
            "--simulate",
            "--auto",
            "--no-cache"
        ])
        
        assert result.exit_code == 0
        
        # Should only process 2 series (both from Uncategorized)
        assert mock_organize_suggest.call_count == 2
        
        # Get the names of processed series
        processed_names = {
            call_args.args[0].name 
            for call_args in mock_organize_suggest.call_args_list
        }
        
        # Should process Series One and Series Two (from Uncategorized)
        # Should NOT process Series Three (from Manga/Action)
        assert processed_names == {"Series One", "Series Two"}
        assert "Series Three" not in processed_names
        
        print("✓ organize --source 'Uncategorized' only processes Uncategorized series")
    
    @patch("vibe_manga.vibe_manga.cli.organize.suggest_category")
    @patch("vibe_manga.vibe_manga.cli.categorize.suggest_category")
    @patch("vibe_manga.vibe_manga.cli.organize.run_scan_with_progress")
    @patch("vibe_manga.vibe_manga.cli.categorize.run_scan_with_progress")
    @patch("vibe_manga.vibe_manga.cli.organize.get_library_root")
    @patch("vibe_manga.vibe_manga.cli.categorize.get_library_root")
    def test_both_commands_handle_empty_uncategorized_equally(
        self,
        mock_categorize_root, mock_organize_root,
        mock_categorize_scan, mock_organize_scan,
        mock_categorize_suggest, mock_organize_suggest
    ):
        """
        Test that both commands handle empty Uncategorized equally.
        
        When no series are in Uncategorized, both should exit gracefully.
        """
        # Create library with NO Uncategorized series
        lib = Library(path=Path("/tmp/lib"), categories=[])
        manga = Category(name="Manga", path=Path("Manga"), sub_categories=[])
        manga_sub = Category(name="Action", path=Path("Manga/Action"), parent=manga, series=[])
        manga.sub_categories.append(manga_sub)
        
        s = Series(name="Series", path=Path("Manga/Action/Series"))
        s.metadata = SeriesMetadata(title="Series", genres=["Action"], mal_id=1)
        manga_sub.series.append(s)
        
        lib.categories = [manga]
        
        mock_categorize_root.return_value = Path("/tmp/lib")
        mock_organize_root.return_value = Path("/tmp/lib")
        mock_categorize_scan.return_value = lib
        mock_organize_scan.return_value = lib
        
        runner = CliRunner()
        
        result_categorize = runner.invoke(cli, [
            "categorize", 
            "--simulate", 
            "--auto",
            "--no-cache"
        ])
        
        result_organize = runner.invoke(cli, [
            "organize",
            "--source", "Uncategorized",
            "--simulate",
            "--auto",
            "--no-cache"
        ])
        
        # Both should succeed but find nothing
        assert result_categorize.exit_code == 0
        assert result_organize.exit_code == 0
        
        # Both should indicate no series found
        assert "No matching series found" in result_categorize.output or "0" in result_categorize.output
        assert "No series matched" in result_organize.output or "0 candidates" in result_organize.output
        
        # Neither should call suggest_category
        assert not mock_categorize_suggest.called
        assert not mock_organize_suggest.called
        
        print("✓ Both commands handle empty Uncategorized equally")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
