#!/usr/bin/env python3
"""Test processing multiple files like generate_transfer_plan does."""
import re
from pathlib import Path
from vibe_manga.vibe_manga.analysis import classify_unit
from vibe_manga.vibe_manga.grabber import vibe_format_range

def process_files(file_list, series_name):
    """Simulates generate_transfer_plan logic."""
    print(f"Series name: '{series_name}'")
    print("-" * 60)
    
    plan = []
    seen_names = set()
    fallback_idx = 1
    
    for path in file_list:
        print(f"\nProcessing: {path}")
        v_nums, ch_nums, u_nums = classify_unit(path)
        print(f"  v_nums: {v_nums}, ch_nums: {ch_nums}, u_nums: {u_nums}")
        
        v_str = vibe_format_range(v_nums, prefix="v", pad=2)
        print(f"  v_str: '{v_str}'")
        
        c_nums = ch_nums
        c_prefix = ""
        if not c_nums and not v_nums and u_nums:
            c_nums = u_nums
            c_prefix = "c"
        
        c_str = vibe_format_range(c_nums, prefix=c_prefix, pad=3)
        print(f"  c_str: '{c_str}'")
        
        parts = []
        if v_str:
            parts.append(v_str)
            print(f"  Added v_str to parts: {parts}")
        if c_str:
            parts.append(c_str)
            print(f"  Added c_str to parts: {parts}")
        
        if not parts:
            parts.append(f"unit{str(fallback_idx).zfill(3)}")
            fallback_idx += 1
            print(f"  No parts, using fallback: {parts}")
        
        base_name = f"{series_name} {' '.join(parts)}"
        print(f"  base_name: '{base_name}'")
        
        ext = Path(path).suffix
        new_name = f"{base_name}{ext}"
        print(f"  new_name: '{new_name}'")
        
        # Collision handling
        collision_idx = 1
        while new_name in seen_names:
            new_name = f"{base_name} ({collision_idx}){ext}"
            collision_idx += 1
        
        seen_names.add(new_name)
        plan.append({"src": Path(path), "dst_name": new_name})
    
    return plan

# Test with the actual files
test_files = [
    "Code of Misconduct c007.cbz",
    "Code of Misconduct c008.cbz",
    "Code of Misconduct c009.cbz",
    "Code of Misconduct c010.cbz",
    "Code of Misconduct c011.cbz",
    "Code of Misconduct c011.5.cbz",
    "Code of Misconduct v01.cbz",
]

# Test with correct series name
print("=" * 60)
print("TEST 1: Correct series name 'Code of Misconduct'")
print("=" * 60)
plan1 = process_files(test_files, "Code of Misconduct")

# Test with problematic series name (what if this is what's happening?)
print("\n\n" + "=" * 60)
print("TEST 2: Problematic series name 'Code of Misconduct .5'")
print("=" * 60)
plan2 = process_files(test_files, "Code of Misconduct .5")

# Show the difference
print("\n\n" + "=" * 60)
print("COMPARISON")
print("=" * 60)
for i, (p1, p2) in enumerate(zip(plan1, plan2)):
    print(f"File {i+1}:")
    print(f"  Correct: {p1['dst_name']}")
    print(f"  Broken:  {p2['dst_name']}")
    print()