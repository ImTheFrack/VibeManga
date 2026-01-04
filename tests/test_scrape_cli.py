from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from vibe_manga.vibe_manga.cli.scrape import scrape
import json
import os

def test_scrape_with_query():
    runner = CliRunner()
    
    # Mock scrape_nyaa to return empty list
    with patch('vibe_manga.vibe_manga.cli.scrape.scrape_nyaa') as mock_scrape, \
         patch('vibe_manga.vibe_manga.cli.scrape.load_query_history', return_value={}), \
         patch('vibe_manga.vibe_manga.cli.scrape.save_query_history'):
        
        mock_scrape.return_value = []
        
        # Run with query that has special chars
        result = runner.invoke(scrape, ['--query', 'Re:Zero'])
        
        assert result.exit_code == 0
        
        # Should call twice: 'Re:Zero' and 'Re Zero'
        assert mock_scrape.call_count == 2
        
        calls = mock_scrape.call_args_list
        args1, kwargs1 = calls[0]
        args2, kwargs2 = calls[1]
        
        assert kwargs1['query'] == 'Re:Zero'
        assert kwargs2['query'] == 'Re Zero'

def test_scrape_no_query():
    runner = CliRunner()
    
    with patch('vibe_manga.vibe_manga.cli.scrape.scrape_nyaa') as mock_scrape, \
         patch('vibe_manga.vibe_manga.cli.scrape.load_query_history', return_value={}), \
         patch('vibe_manga.vibe_manga.cli.scrape.save_query_history'):
        
        mock_scrape.return_value = []
        
        result = runner.invoke(scrape, [])
        
        assert result.exit_code == 0
        assert mock_scrape.call_count == 1
        # Should be called with query=None
        assert mock_scrape.call_args[1]['query'] is None
