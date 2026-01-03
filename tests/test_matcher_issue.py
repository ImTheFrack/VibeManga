import pytest
from vibe_manga.vibe_manga.matcher import parse_entry

def test_persona_5_overstripping():
    entry = {
        "name": "Persona 5 v01-14 + 084.1-099.1 (2020-2025) (Digital) (1r0n)",
        "size": "3.3 GiB"
    }
    parsed = parse_entry(entry)
    
    assert "Persona 5" in parsed["parsed_name"], f"Expected 'Persona 5' in parsed names, got {parsed['parsed_name']}"
    assert "Persona" not in parsed["parsed_name"], f"Should not have stripped the '5' from 'Persona 5'. Got {parsed['parsed_name']}"
    assert parsed["volume_begin"] == "01"
    assert parsed["volume_end"] == "14"
    assert parsed["chapter_begin"] == "084.1"
    assert parsed["chapter_end"] == "099.1"

def test_standard_naked_chapter():
    entry = {
        "name": "One Piece 1000",
        "size": "50 MB"
    }
    parsed = parse_entry(entry)
    # Without prefix, 1000 should be stripped
    assert "One Piece" in parsed["parsed_name"]
    assert "1000" not in parsed["parsed_name"][0]
    assert parsed["chapter_begin"] == "1000"

def test_manga_5_v1_10():
    entry = {
        "name": "Manga 5 v1 10",
        "size": "200 MB"
    }
    parsed = parse_entry(entry)
    # 10 should be stripped (naked after prefix), 5 should be protected (before prefix)
    assert "Manga 5" in parsed["parsed_name"]
    assert parsed["volume_begin"] == "1"
    assert parsed["chapter_begin"] == "10"

def test_20th_century_boys_v1():
    entry = {
        "name": "20th Century Boys v1",
        "size": "200 MB"
    }
    parsed = parse_entry(entry)
    assert "20th Century Boys" in parsed["parsed_name"]
    assert parsed["volume_begin"] == "1"

def test_multiple_naked_no_prefix():
    entry = {
        "name": "Manga 5 10",
        "size": "50 MB"
    }
    parsed = parse_entry(entry)
    # Should strip 10, then 5 (existing behavior for ambiguous strings)
    assert "Manga" in parsed["parsed_name"]
    assert parsed["chapter_begin"] == "10"
    assert any("Extra Chapter: 5" in n for n in parsed["notes"])

if __name__ == "__main__":
    # Manual run for debugging
    test_persona_5_overstripping()
    test_standard_naked_chapter()
    test_manga_5_v1_10()
    test_20th_century_boys_v1()
    test_multiple_naked_no_prefix()
    print("All tests passed!")