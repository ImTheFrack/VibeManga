"""
Grab command for VibeManga CLI.

Selects a manga from matched results and adds it to qBittorrent.
"""
import click
from typing import Optional

from .base import get_library_root
from ..grabber import process_grab

@click.command()
@click.argument("name", required=False)
@click.option("--input-file", default="nyaa_match_results.json", help="Matched results JSON.")
@click.option("--status", is_flag=True, help="Show current qBittorrent downloads for VibeManga.")
@click.option("--auto-add", is_flag=True, help="Automatically add torrents if they contain new volumes.")
@click.option("--auto-add-only", is_flag=True, help="Same as auto-add, but skips items that don't match criteria instead of prompting.")
@click.option("--force", is_flag=True, help="Process items even if they were previously marked for skipping in auto-add modes.")
@click.option("--max", "max_downloads", type=int, help="Limit the number of auto-added items.")
def grab(name: Optional[str], input_file: str, status: bool, auto_add: bool, auto_add_only: bool, force: bool, max_downloads: Optional[int]) -> None:
    """
    Selects a manga from matched results and adds it to qBittorrent.
    
    NAME can be a parsed name from the JSON or 'next' to get the first unflagged entry.
    """
    root_path = get_library_root()
    process_grab(name, input_file, status, root_path, auto_add=auto_add, auto_add_only=auto_add_only, force=force, max_downloads=max_downloads)
