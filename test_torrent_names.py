#!/usr/bin/env python3
"""Test parse_entry with a torrent name that includes a chapter number."""
from vibe_manga.vibe_manga.matcher import parse_entry

# What if the torrent was named after a specific file?
test_cases = [
    "Code of Misconduct (Digital) (Oak)",
    "Code of Misconduct c011.5",
    "Code of Misconduct c011.5 (Digital)",
    "Code of Misconduct vol 1-2",
]

for name in test_cases:
    entry = {"name": name}
    print(f"\n{'='*60}")
    print(f"Input: {name}")
    print(f"{'='*60}")
    
    result = parse_entry(entry)
    
    print(f"parsed_name: {result['parsed_name']}")
    print(f"chapter_begin: {result['chapter_begin']}")
    print(f"chapter_end: {result['chapter_end']}")
    print(f"volume_begin: {result['volume_begin']}")
    print(f"volume_end: {result['volume_end']}")