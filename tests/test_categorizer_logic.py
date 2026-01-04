
import pytest
from unittest.mock import MagicMock, patch, call
from vibe_manga.vibe_manga.categorizer import suggest_category
from vibe_manga.vibe_manga.models import Series, Library, Category
from vibe_manga.vibe_manga.metadata import SeriesMetadata

@pytest.fixture
def mock_series_and_library():
    series = Series(name="Test Manga", path=MagicMock())
    
    lib = Library(path=MagicMock(), categories=[])
    cat = Category(name="Manga", path=MagicMock(), sub_categories=[])
    sub = Category(name="Action", path=MagicMock(), parent=cat, series=[])
    cat.sub_categories.append(sub)
    lib.categories.append(cat)
    
    return series, lib

@patch("vibe_manga.vibe_manga.categorizer.call_ai")
@patch("vibe_manga.vibe_manga.categorizer.get_or_create_metadata")
def test_suggest_category_auto_retry_on_invalid_category(mock_meta, mock_call_ai, mock_series_and_library):
    """
    Test that suggest_category (in auto mode) rejects a category not in the list 
    and retries with a warning.
    """
    series, library = mock_series_and_library
    
    # Mock metadata
    meta = SeriesMetadata(title="Test Manga", genres=["Action"])
    mock_meta.return_value = (meta, "test_source")
    
    # Define AI responses sequence
    # 1. Moderator (Safe)
    # 2. Practical (Valid)
    # 3. Creative (Valid)
    # 4. Consensus Attempt 1: "Manga/Hallucinated" (INVALID)
    # 5. Consensus Attempt 2: "Manga/Action" (VALID)
    
    mock_call_ai.side_effect = [
        {"classification": "SAFE"}, # Mod
        {"category": "Manga/Action"}, # Prac
        {"category": "Manga/Action"}, # Crea
        # Consensus 1: Invalid
        {
            "final_category": "Manga",
            "final_sub_category": "Hallucinated",
            "reason": "I made this up",
            "confidence_score": 0.5
        },
        # Consensus 2: Valid
        {
            "final_category": "Manga",
            "final_sub_category": "Action",
            "reason": "Corrected choice",
            "confidence_score": 0.9
        }
    ]
    
    # Run WITHOUT confirm_callback (Auto Mode)
    result = suggest_category(series, library, quiet=True)
    
    # Assertions
    assert result is not None
    consensus = result.get("consensus")
    assert consensus["final_sub_category"] == "Action"
    
    # Check call arguments to verify the retry prompt contained the warning
    # We expect 5 calls total. The last one is the retry.
    assert mock_call_ai.call_count == 5
    
    last_call_args = mock_call_ai.call_args_list[-1]
    prompt_sent = last_call_args[0][0] # First arg is prompt
    
    assert "The suggested category 'Manga/Hallucinated' is NOT in the Official Category List" in prompt_sent
    assert "You MUST strictly choose one from the 'Official Category List'" in prompt_sent

@patch("vibe_manga.vibe_manga.categorizer.call_ai")
@patch("vibe_manga.vibe_manga.categorizer.get_or_create_metadata")
def test_suggest_category_interactive_accept(mock_meta, mock_call_ai, mock_series_and_library):
    """
    Test that interactive mode allows new category if user accepts.
    """
    series, library = mock_series_and_library
    mock_meta.return_value = (SeriesMetadata(title="Test"), "src")
    
    mock_call_ai.side_effect = [
        {"classification": "SAFE"},
        {}, {},
        # Consensus 1: New Category
        {
            "final_category": "Manga",
            "final_sub_category": "NewOne",
            "reason": "New",
            "confidence_score": 0.8
        }
    ]
    
    # User accepts
    confirm_cb = MagicMock(return_value=True)
    
    result = suggest_category(series, library, quiet=True, confirm_callback=confirm_cb)
    
    # Should accept immediately (4 calls total)
    assert mock_call_ai.call_count == 4
    assert result["consensus"]["final_sub_category"] == "NewOne"
    confirm_cb.assert_called_once()

@patch("vibe_manga.vibe_manga.categorizer.call_ai")
@patch("vibe_manga.vibe_manga.categorizer.get_or_create_metadata")
def test_suggest_category_interactive_reject(mock_meta, mock_call_ai, mock_series_and_library):
    """
    Test that interactive mode retries if user rejects.
    """
    series, library = mock_series_and_library
    mock_meta.return_value = (SeriesMetadata(title="Test"), "src")
    
    mock_call_ai.side_effect = [
        {"classification": "SAFE"},
        {}, {},
        # Consensus 1: New Category
        {
            "final_category": "Manga",
            "final_sub_category": "NewOne",
            "reason": "New",
            "confidence_score": 0.8
        },
        # Consensus 2: Valid
        {
            "final_category": "Manga",
            "final_sub_category": "Action",
            "reason": "Ok",
            "confidence_score": 1.0
        }
    ]
    
    # User REJECTS
    confirm_cb = MagicMock(return_value=False)
    
    result = suggest_category(series, library, quiet=True, confirm_callback=confirm_cb)
    
    # Should retry (5 calls total)
    assert mock_call_ai.call_count == 5
    assert result["consensus"]["final_sub_category"] == "Action"
    
    # Verify rejection prompt
    last_call_args = mock_call_ai.call_args_list[-1]
    prompt_sent = last_call_args[0][0]
    assert "The user REJECTED the new category 'Manga/NewOne'" in prompt_sent
