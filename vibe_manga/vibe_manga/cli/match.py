"""
Match command for VibeManga CLI.

Parses scraped data to extract manga info and match against library.
"""
import click
import logging
from typing import Optional

from .base import run_scan_with_progress, get_library_root
from ..matcher import process_match
from ..constants import NYAA_DEFAULT_OUTPUT_FILENAME

logger = logging.getLogger(__name__)

@click.command()
@click.argument("query", required=False)
@click.option("--input-file", default=NYAA_DEFAULT_OUTPUT_FILENAME, help="Input JSON file (default: nyaa_scrape_results.json)")
@click.option("--output-file", default="nyaa_match_results.json", help="Output JSON file.")
@click.option("--table", is_flag=True, help="Show the results table.")
@click.option("--all", "show_all", is_flag=True, help="Show all entries, including skipped ones.")
@click.option("--no-cache", is_flag=True, help="Force fresh scan for matching logic.")
@click.option("--stats", is_flag=True, help="Show a visually compelling summary of match statistics.")
@click.option("--no-parallel", is_flag=True, help="Disable parallel matching (slower).")
def match(query: Optional[str], input_file: str, output_file: str, table: bool, show_all: bool, no_cache: bool, stats: bool, no_parallel: bool) -> None:
    """
    Parses scraped data to extract manga info.
    If QUERY is provided, only matches against library series matching that name.
    """
    logger.info(f"Match command started (query={query}, input={input_file}, output={output_file}, table={table}, show_all={show_all}, no_cache={no_cache}, stats={stats}, no_parallel={no_parallel})")
    
    # Run scan with progress for better UX
    root_path = get_library_root()
    library = run_scan_with_progress(
        root_path,
        "[bold green]Scanning Library for Matching...",
        use_cache=not no_cache
    )
    
    process_match(input_file, output_file, table, show_all, library=library, show_stats=stats, query=query, parallel=not no_parallel)
