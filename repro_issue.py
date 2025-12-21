
import re
import sys
import os

# Add current directory to path so we can import the project
sys.path.append(os.getcwd())

from vibe_manga.vibe_manga.analysis import semantic_normalize

def find_series_match_logic(torrent_name: str, library_series_names: list[str]) -> str | None:
    norm_t_name = semantic_normalize(torrent_name)
    print(f"Normalized Scraped Name: '{norm_t_name}'")
    
    for s_name in library_series_names:
        norm_s_name = semantic_normalize(s_name)
        # This mimics the logic in vibe_manga/vibe_manga/grabber.py:find_series_match
        if norm_s_name and norm_s_name in norm_t_name:
            print(f"  -> FOUND SUBSTRING MATCH: '{norm_s_name}' (from '{s_name}') is in '{norm_t_name}'")
            return s_name
    return None

def main():
    torrent_name = "Adam Warren's Dirty Pair"
    library_series_names = ["Dirty Pair", "Other Series"]
    
    print(f"Testing Scraped Torrent: '{torrent_name}'")
    match = find_series_match_logic(torrent_name, library_series_names)
    
    if match:
        print(f"\nRESULT: Falsely matched to '{match}'")
    else:
        print("\nRESULT: No match found")

if __name__ == "__main__":
    main()
