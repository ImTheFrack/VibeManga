"""
Pullcomplete command for VibeManga CLI.

Runs a full update cycle: pull -> stats -> metadata -> categorize.
"""
import click
import logging
from rich.rule import Rule

from .base import console, get_library_root, run_scan_with_progress
# These are needed for ctx.invoke()
from .pull import pull
from .stats import stats
from .metadata import metadata
from .categorize import categorize
from .scrape import scrape
from .match import match
from .grab import grab

from ..qbit_api import QBitAPI
from ..constants import (
    QBIT_DEFAULT_TAG,
    NYAA_DEFAULT_PAGES_TO_SCRAPE,
    NYAA_DEFAULT_OUTPUT_FILENAME
)

logger = logging.getLogger(__name__)

@click.command()
@click.option("--input-file", default="nyaa_match_results.json", help="Matched results JSON to update status.")
@click.pass_context
def pullcomplete(ctx, input_file: str) -> None:
    """
    Runs a full update cycle: pull -> stats -> metadata -> categorize.
    Then checks download queue and replenishes if < 150 active torrents.
    """
    console.print(Rule("[bold magenta]Starting Full Update Cycle[/bold magenta]"))
    
    # 1. Pull
    console.print("\n[bold cyan]Step 1/6: Pulling Completed Torrents[/bold cyan]")
    ctx.invoke(pull, input_file=input_file, simulate=False, pause=False)
    
    # 2. Refresh Cache (Silent Scan)
    console.print("\n[bold cyan]Step 2/6: Refreshing Library Cache[/bold cyan]")
    root = get_library_root()
    # We run the scan directly to update cache without printing the full stats report
    run_scan_with_progress(root, "[bold green]Refreshing Cache...[/bold green]", use_cache=False)
    
    # 3. Metadata
    console.print("\n[bold cyan]Step 3/6: Updating Metadata[/bold cyan]")
    ctx.invoke(metadata, query=None, force_update=False, trust_jikan=False, process_all=True, model_assign=False)
    
    # 4. Categorize
    console.print("\n[bold cyan]Step 4/6: Auto-Categorizing[/bold cyan]")
    ctx.invoke(categorize, query=None, auto=True, simulate=False, no_cache=True, model_assign=False, pause=False)
    
    # 5. Replenish
    console.print("\n[bold cyan]Step 5/6: Checking Download Queue[/bold cyan]")
    try:
        qbit = QBitAPI()
        torrents = qbit.get_torrents_info(tag=QBIT_DEFAULT_TAG)
        count = len(torrents)
        LIMIT = 150
        
        if count < LIMIT:
            needed = LIMIT - count
            console.print(f"[green]Queue has {count} items. Replenishing up to {LIMIT} (Need {needed})...[/green]")
            
            # a. Scrape
            console.print("[dim]Running Scrape...[/dim]")
            ctx.invoke(scrape, pages=NYAA_DEFAULT_PAGES_TO_SCRAPE, output=NYAA_DEFAULT_OUTPUT_FILENAME, user_agent=None, force=False, summarize=False)
            
            # b. Match
            console.print("[dim]Running Match...[/dim]")
            ctx.invoke(match, query=None, input_file=NYAA_DEFAULT_OUTPUT_FILENAME, output_file=input_file, table=False, show_all=False, no_cache=True, stats=False, no_parallel=False)
            
            # c. Grab
            console.print(f"[dim]Running Grab (Auto-Add Max {needed})...[/dim]")
            ctx.invoke(grab, name=None, input_file=input_file, status=False, auto_add=False, auto_add_only=True, max_downloads=needed)
            
        else:
            console.print(f"[yellow]Queue is full ({count} >= {LIMIT}). Skipping replenishment.[/yellow]")
            
    except Exception as e:
        console.print(f"[red]Error during replenishment step: {e}[/red]")
        logger.error(f"Replenish failed: {e}", exc_info=True)

    # 6. Final Stats
    console.print("\n[bold cyan]Step 6/6: Final Library Statistics[/bold cyan]")
    # We use no_cache=True to ensure we see the result of any moves done by Categorize
    ctx.invoke(stats, query=None, continuity=False, deep=False, verify=False, no_cache=True, no_metadata=False)

    console.print(Rule("[bold green]Full Update Cycle Complete[/bold green]"))
