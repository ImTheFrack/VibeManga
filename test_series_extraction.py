#!/usr/bin/env python3
"""Test script to reproduce the series name extraction issue."""
import re
from pathlib import Path
from vibe_manga.vibe_manga.analysis import sanitize_filename

def extract_series_name(display_name):
    """Simulates the series name extraction from process_pull."""
    print(f"\nInput display_name: '{display_name}'")
    
    # Step 1: Remove Rich tags
    step1 = re.sub(r"\[.*?\]", "", display_name).strip()
    print(f"After removing Rich tags: '{step1}'")
    
    # Step 2: Remove leading number
    step2 = re.sub(r"^\d+\.\s+", "", step1)
    print(f"After removing leading number: '{step2}'")
    
    # Step 3: Sanitize
    step3 = sanitize_filename(step2)
    print(f"After sanitization: '{step3}'")
    
    return step3

# Test cases that might reveal the issue
test_cases = [
    # Normal case
    "Code of Misconduct",
    
    # With Rich tags (as would come from get_matched_or_parsed_name)
    "[green]Code of Misconduct[/green]",
    
    # What if the torrent name includes a chapter number?
    "Code of Misconduct c011.5",
    "[green]Code of Misconduct c011.5[/green]",
    
    # What if it's parsed weirdly?
    "Code of Misconduct .5",
    "[green]Code of Misconduct .5[/green]",
    
    # With numbering prefix (as added in the torrent list)
    "1. Code of Misconduct",
    "1. [green]Code of Misconduct[/green]",
    
    # The actual torrent name might be
    "Code of Misconduct (Digital) (Oak)",
    "[green]Code of Misconduct (Digital) (Oak)[/green]",
]

for test in test_cases:
    result = extract_series_name(test)
    print(f"Final result: '{result}'")
    print("-" * 60)