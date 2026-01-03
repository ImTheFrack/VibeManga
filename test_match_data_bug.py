#!/usr/bin/env python3
"""Test what happens if match_data has an incorrect matched_name."""
import re
from vibe_manga.vibe_manga.grabber import get_matched_or_parsed_name
from vibe_manga.vibe_manga.models import Series, Category, SubGroup

# Simulate a library
library = None  # New series, no library match

# Simulate match_data with an incorrect matched_name
# This could happen if the match command incorrectly parsed something
match_data = [
    {
        "name": "Code of Misconduct (Digital) (Oak)",
        "matched_name": "Code of Misconduct .5",  # This is wrong!
        "matched_id": None,
    }
]

series_map = {}

torrent_name = "Code of Misconduct (Digital) (Oak)"

print(f"Torrent name: {torrent_name}")
print(f"Match data: {match_data}")
print()

result = get_matched_or_parsed_name(torrent_name, library, match_data, series_map)

print(f"Result: '{result}'")
print()

# Now extract series name like process_pull does
series_name = re.sub(r"\[.*?\]", "", result).strip()
series_name = re.sub(r"^\d+\.\s+", "", series_name)

from vibe_manga.vibe_manga.analysis import sanitize_filename
series_name = sanitize_filename(series_name)

print(f"Extracted series_name: '{series_name}'")