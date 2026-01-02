"""
Pull command for VibeManga CLI.

Checks for completed torrents in qBittorrent and post-processes them.
"""
import click

from .base import get_library_root
from ..grabber import process_pull

@click.command()
@click.option("--input-file", default="nyaa_match_results.json", help="Matched results JSON to update status.")
@click.option("--simulate", is_flag=True, help="Show what would be done without making changes.")
@click.option("--pause", is_flag=True, help="Pause between post-processing items.")
def pull(input_file: str, simulate: bool, pause: bool) -> None:
    """
    Checks for completed torrents in qBittorrent and post-processes them.
    """
    root_path = get_library_root()
    process_pull(simulate=simulate, pause=pause, root_path=root_path, input_file=input_file)
