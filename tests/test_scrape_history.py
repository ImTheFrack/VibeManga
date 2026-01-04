import json
import time
from unittest.mock import patch, mock_open, MagicMock
from click.testing import CliRunner
from vibe_manga.vibe_manga.cli.scrape import scrape, SCRAPE_HISTORY_FILENAME, SCRAPE_QUERY_COOLDOWN_DAYS

def test_scrape_history_update():
    runner = CliRunner()
    
    # Mock no existing history
    mock_history = {}
    
    with patch('vibe_manga.vibe_manga.cli.scrape.load_query_history', return_value=mock_history), \
         patch('vibe_manga.vibe_manga.cli.scrape.save_query_history') as mock_save, \
         patch('vibe_manga.vibe_manga.cli.scrape.scrape_nyaa', return_value=[]) as mock_scrape_nyaa:
        
        # Run with query
        result = runner.invoke(scrape, ['-q', 'TestQuery'])
        
        assert result.exit_code == 0
        assert mock_scrape_nyaa.called
        assert mock_save.called
        
        # Check that history was updated
        saved_history = mock_save.call_args[0][0]
        assert 'TestQuery' in saved_history
        # Timestamp should be recent
        assert saved_history['TestQuery'] > 0

def test_scrape_history_cooldown():
    runner = CliRunner()
    
    # Mock history with recent run
    recent_ts = time.time() - 100 # 100 seconds ago
    mock_history = {'TestQuery': recent_ts}
    
    with patch('vibe_manga.vibe_manga.cli.scrape.load_query_history', return_value=mock_history), \
         patch('vibe_manga.vibe_manga.cli.scrape.save_query_history') as mock_save, \
         patch('vibe_manga.vibe_manga.cli.scrape.scrape_nyaa', return_value=[]) as mock_scrape_nyaa:
        
        # Run with same query
        result = runner.invoke(scrape, ['-q', 'TestQuery'])
        
        assert result.exit_code == 0
        # Should NOT scrape
        assert not mock_scrape_nyaa.called
        # Should NOT save (no update)
        assert not mock_save.called

def test_scrape_history_force_bypass():
    runner = CliRunner()
    
    # Mock history with recent run
    recent_ts = time.time() - 100
    mock_history = {'TestQuery': recent_ts}
    
    with patch('vibe_manga.vibe_manga.cli.scrape.load_query_history', return_value=mock_history), \
         patch('vibe_manga.vibe_manga.cli.scrape.save_query_history') as mock_save, \
         patch('vibe_manga.vibe_manga.cli.scrape.scrape_nyaa', return_value=[]) as mock_scrape_nyaa:
        
        # Run with force
        result = runner.invoke(scrape, ['-q', 'TestQuery', '--force'])
        
        assert result.exit_code == 0
        # Should scrape
        assert mock_scrape_nyaa.called
        # Should save (update timestamp)
        assert mock_save.called
        saved_history = mock_save.call_args[0][0]
        assert saved_history['TestQuery'] > recent_ts

def test_scrape_history_expired_cooldown():
    runner = CliRunner()
    
    # Mock history with OLD run (31 days ago)
    old_ts = time.time() - (31 * 24 * 3600)
    mock_history = {'TestQuery': old_ts}
    
    with patch('vibe_manga.vibe_manga.cli.scrape.load_query_history', return_value=mock_history), \
         patch('vibe_manga.vibe_manga.cli.scrape.save_query_history') as mock_save, \
         patch('vibe_manga.vibe_manga.cli.scrape.scrape_nyaa', return_value=[]) as mock_scrape_nyaa:
        
        # Run
        result = runner.invoke(scrape, ['-q', 'TestQuery'])
        
        assert result.exit_code == 0
        # Should scrape
        assert mock_scrape_nyaa.called
        assert mock_save.called

