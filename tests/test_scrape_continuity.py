from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from vibe_manga.vibe_manga.cli.scrape import scrape
from vibe_manga.vibe_manga.models import Series, SeriesMetadata, Category, Library
from pathlib import Path

def test_scrape_continuity():
    runner = CliRunner()
    
    # Setup Mock Data
    meta_complete = SeriesMetadata(title="Complete Series")
    s1 = Series(name="Complete Series", path=Path("/tmp/s1"), metadata=meta_complete)
    
    meta_incomplete = SeriesMetadata(title="Incomplete Series")
    s2 = Series(name="Incomplete Series", path=Path("/tmp/s2"), metadata=meta_incomplete)
    
    # Mock Library Structure
    sub_cat = Category(name="Sub", path=Path("/tmp/sub"), series=[s1, s2])
    cat = Category(name="Main", path=Path("/tmp/main"), sub_categories=[sub_cat])
    library = Library(path=Path("/tmp/lib"), categories=[cat])
    
    # Mock dependencies
    with patch('vibe_manga.vibe_manga.cli.scrape.run_scan_with_progress', return_value=library), \
         patch('vibe_manga.vibe_manga.cli.scrape.get_library_root', return_value=Path("/tmp")), \
         patch('vibe_manga.vibe_manga.cli.scrape.find_gaps') as mock_find_gaps, \
         patch('vibe_manga.vibe_manga.cli.scrape.scrape_nyaa', return_value=[]) as mock_scrape_nyaa, \
         patch('vibe_manga.vibe_manga.cli.scrape.load_query_history', return_value={}), \
         patch('vibe_manga.vibe_manga.cli.scrape.save_query_history'):
         
        # Configure find_gaps
        def side_effect(series):
            if series.name == "Incomplete Series":
                return ["Missing Vol 1"]
            return []
        mock_find_gaps.side_effect = side_effect
        
        # Run command
        result = runner.invoke(scrape, ['--continuity'])
        
        assert result.exit_code == 0
        
        # Verify scrape calls
        # Should scrape for "Incomplete Series"
        # "Complete Series" should be skipped
        
        # Collect all query args passed to scrape_nyaa
        called_queries = [call.kwargs.get('query') for call in mock_scrape_nyaa.call_args_list]
        
        # Flatten list if needed (though queries are passed one by one)
        print(f"Called queries: {called_queries}")
        
        assert "Incomplete Series" in called_queries
        assert "Complete Series" not in called_queries
        
        # Also verify alternatives are generated
        # Incomplete Series -> Incomplete Series (Sanitized same), Keywords: Incomplete Series
        # Should be called.
        
        # Verify that default scrape (None) was NOT called because continuity found targets
        assert None not in called_queries
