"""
Pull command for VibeManga CLI.

Checks for completed torrents in qBittorrent and post-processes them.
"""
import click
import logging
from .base import get_library_root, console
from ..grabber import process_pull
from ..logging import set_log_level

@click.command()
@click.option("--input-file", default="nyaa_match_results.json", help="Matched results JSON to update status.")
@click.option("--simulate", is_flag=True, help="Show what would be done without making changes.")
@click.option("--pause", is_flag=True, help="Pause between post-processing items.")
@click.option("-v", "--verbose", count=True, help="Increase verbosity (-v: INFO, -vv: DEBUG).")
def pull(input_file: str, simulate: bool, pause: bool, verbose: int) -> None:
    """
    Checks for completed torrents in qBittorrent and post-processes them.
    """
    # Set global verbosity based on flag
    log_level = logging.WARNING
    clean_logs = False
    if verbose == 1:
        log_level = logging.INFO
        clean_logs = True
    elif verbose >= 2:
        log_level = logging.DEBUG
        clean_logs = False
        
    set_log_level(log_level, "console", clean=clean_logs)

    root_path = get_library_root()
    process_pull(simulate=simulate, pause=pause, root_path=root_path, input_file=input_file)
