#!/usr/bin/env python3
"""Test script to reproduce the Code of Misconduct naming issue."""
import re
from pathlib import Path
from vibe_manga.vibe_manga.analysis import classify_unit
from vibe_manga.vibe_manga.grabber import vibe_format_range

def test_classify_and_format(filename, series_name):
    """Simulates the generate_transfer_plan logic."""
    print(f"\n=== Testing: {filename} ===")
    
    # Step 1: Classify units
    v_nums, ch_nums, u_nums = classify_unit(filename)
    print(f"v_nums: {v_nums}")
    print(f"ch_nums: {ch_nums}")
    print(f"u_nums: {u_nums}")
    
    # Step 2: Format volume string
    v_str = vibe_format_range(v_nums, prefix="v", pad=2)
    print(f"v_str: '{v_str}'")
    
    # Step 3: Handle chapters/units
    c_nums = ch_nums
    c_prefix = ""
    if not c_nums and not v_nums and u_nums:
        c_nums = u_nums
        c_prefix = "c"
    
    c_str = vibe_format_range(c_nums, prefix=c_prefix, pad=3)
    print(f"c_str: '{c_str}'")
    
    # Step 4: Build parts list
    parts = []
    if v_str:
        parts.append(v_str)
        print(f"Added to parts: '{v_str}'")
    if c_str:
        parts.append(c_str)
        print(f"Added to parts: '{c_str}'")
    
    if not parts:
        print("No parts found - would use fallback")
    
    print(f"parts: {parts}")
    
    # Step 5: Build base name
    base_name = f"{series_name} {' '.join(parts)}"
    print(f"base_name: '{base_name}'")
    
    # Step 6: Final name
    ext = Path(filename).suffix
    new_name = f"{base_name}{ext}"
    print(f"Final new_name: '{new_name}'")
    
    return new_name

# Test cases from the user's report
test_files = [
    "Code of Misconduct c007.cbz",
    "Code of Misconduct c008.cbz",
    "Code of Misconduct c009.cbz",
    "Code of Misconduct c010.cbz",
    "Code of Misconduct c011.cbz",
    "Code of Misconduct c011.5.cbz",
    "Code of Misconduct v01.cbz",
]

series_name = "Code of Misconduct"

for test_file in test_files:
    test_classify_and_format(test_file, series_name)
