#!/usr/bin/env python3
"""Test sanitize_filename with various inputs including decimals."""
from vibe_manga.vibe_manga.analysis import sanitize_filename

test_cases = [
    "Code of Misconduct",
    "Code of Misconduct .5",
    "Code of Misconduct c011.5",
    "Code of Misconduct 11.5",
    ".5",
    "c011.5",
    "11.5",
]

for test in test_cases:
    result = sanitize_filename(test)
    print(f"'{test}' -> '{result}'")