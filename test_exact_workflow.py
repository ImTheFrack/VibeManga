#!/usr/bin/env python3
"""Simulate the exact series name extraction from process_pull."""
import re
from vibe_manga.vibe_manga.analysis import sanitize_filename

def simulate_process_pull_series_name_extraction(torrent_name, library=None, match_data=None, series_map=None):
    """
    Simulates the exact series name extraction logic from process_pull.
    This is what happens in Step 3 of process_pull.
    """
    print(f"\n{'='*70}")
    print(f"Testing torrent: {torrent_name}")
    print(f"{'='*70}")
    
    # Step 1: Get display name (from get_matched_or_parsed_name)
    # For this test, we'll simulate what get_matched_or_parsed_name returns
    # In the real code, this would check match_data, library, etc.
    # But for new series, it would fallback to parsing
    
    # Simulate parse_entry being called and returning parsed names
    # For this test, let's assume it returns the clean series name
    # But what if it doesn't...
    
    # Let's trace what actually happens in get_matched_or_parsed_name
    # when there's no library match and no match_data...
    
    from vibe_manga.vibe_manga.matcher import parse_entry
    
    # This is what happens in get_matched_or_parsed_name line 76-101
    parsed = parse_entry({"name": torrent_name})
    parsed_names = parsed.get("parsed_name", [])
    print(f"parse_entry returned: {parsed_names}")
    
    if parsed_names and not any(n.startswith("SKIPPED:") for n in parsed_names):
        # Filter out substrings...
        unique_names = []
        sorted_candidates = sorted(list(set(parsed_names)), key=len, reverse=True)
        
        for candidate in sorted_candidates:
            is_substring = False
            for selected in unique_names:
                if candidate in selected:
                    is_substring = True
                    break
            
            if not is_substring:
                unique_names.append(candidate)
        
        display_name = " | ".join(unique_names)
    else:
        display_name = torrent_name
    
    print(f"display_name: '{display_name}'")
    
    # Step 2: Extract series name (from process_pull lines 838-841)
    series_name = re.sub(r"\[.*?\]", "", display_name).strip()
    print(f"After removing Rich tags: '{series_name}'")
    
    series_name = re.sub(r"^\d+\.\s+", "", series_name)
    print(f"After removing leading number: '{series_name}'")
    
    series_name = sanitize_filename(series_name)
    print(f"After sanitization: '{series_name}'")
    
    return series_name

# Test with different possible torrent names
test_cases = [
    # Expected case
    "Code of Misconduct (Digital) (Oak)",
    
    # What if qBittorrent has a different name?
    "Code of Misconduct c011.5 (Digital) (Oak)",
    "Code of Misconduct c011.5",
    
    # What if it's from match_data and has weird formatting?
    # (We'll simulate this by just passing it through)
]

for test in test_cases:
    result = simulate_process_pull_series_name_extraction(test)
    print(f"FINAL RESULT: '{result}'")