#!/usr/bin/env python3
"""Test what parse_entry does with 'Code of Misconduct (Digital) (Oak)'"""
import re
from vibe_manga.vibe_manga.matcher import parse_entry

# Simulate the entry dict
entry = {"name": "Code of Misconduct (Digital) (Oak)"}

print(f"Input: {entry['name']}\n")

result = parse_entry(entry)

print(f"parsed_name: {result['parsed_name']}")
print(f"type: {result['type']}")
print(f"volume_begin: {result['volume_begin']}")
print(f"volume_end: {result['volume_end']}")
print(f"chapter_begin: {result['chapter_begin']}")
print(f"chapter_end: {result['chapter_end']}")
print(f"notes: {result['notes']}")