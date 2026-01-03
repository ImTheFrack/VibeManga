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
from ..logging import get_logger, set_log_level, temporary_log_level, log_step

logger = get_logger(__name__)

@click.command()
@click.option("--input-file", default="nyaa_match_results.json", help="Matched results JSON to update status.")
@click.option("-v", "--verbose", count=True, help="Increase verbosity (-v: INFO, -vv: DEBUG).")
@click.pass_context
def pullcomplete(ctx, input_file: str, verbose: int) -> None:
    """
    Runs a full update cycle: pull -> stats -> metadata -> categorize.
    Then checks download queue and replenishes if < 150 active torrents.
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
    
    # Also log start to file via logger, not just console print
    logger.info("Starting Full Update Cycle")
    if verbose > 0:
        log_step("Starting Full Update Cycle")
    else:
        console.print(Rule("[bold magenta]Starting Full Update Cycle[/bold magenta]"))
    
    # Helper to wrap steps
    def run_step(step_name, func, **kwargs):
        msg = f"{step_name}"
        if verbose > 0:
            log_step(msg)
        else:
            console.print(f"\n[bold cyan]{msg}[/bold cyan]")
            
        with temporary_log_level(log_level):
            if func:
                ctx.invoke(func, **kwargs)

    # 1. Pull
    run_step("Step 1/6: Pulling Completed Torrents", pull, input_file=input_file, simulate=False, pause=False, verbose=verbose)
    
    # 2. Refresh Cache (Silent Scan)
    msg = "Step 2/6: Refreshing Library Cache"
    if verbose > 0:
        log_step(msg)
    else:
        console.print(f"\n[bold cyan]{msg}[/bold cyan]")
        
    with temporary_log_level(log_level):
        root = get_library_root()
        # We run the scan directly to update cache without printing the full stats report
        run_scan_with_progress(root, "[bold green]Refreshing Cache...[/bold green]", use_cache=False)
    
    # 3. Metadata
    run_step("Step 3/6: Updating Metadata", metadata, query=None, force_update=False, trust_jikan=False, process_all=True, model_assign=False)
    
    # 4. Categorize
    run_step("Step 4/6: Auto-Categorizing", categorize, query=None, auto=True, simulate=False, no_cache=True, model_assign=False, pause=False)
    
    # 5. Replenish
    msg = "Step 5/6: Checking Download Queue"
    if verbose > 0:
        log_step(msg)
    else:
        console.print(f"\n[bold cyan]{msg}[/bold cyan]")
        
    with temporary_log_level(log_level):
        try:
            qbit = QBitAPI()
            torrents = qbit.get_torrents_info(tag=QBIT_DEFAULT_TAG)
            count = len(torrents)
            LIMIT = 150
            
            if count < LIMIT:
                needed = LIMIT - count
                console.print(f"[green]Queue has {count} items. Replenishing up to {LIMIT} (Need {needed})...[/green]")
                
                # a. Scrape
                if verbose == 0: console.print("[dim]Running Scrape...[/dim]")
                ctx.invoke(scrape, pages=NYAA_DEFAULT_PAGES_TO_SCRAPE, output=NYAA_DEFAULT_OUTPUT_FILENAME, user_agent=None, force=False, summarize=False)
                
                # b. Match
                if verbose == 0: console.print("[dim]Running Match...[/dim]")
                ctx.invoke(match, query=None, input_file=NYAA_DEFAULT_OUTPUT_FILENAME, output_file=input_file, table=False, show_all=False, no_cache=True, stats=False, no_parallel=False)
                
                # c. Grab
                if verbose == 0: console.print(f"[dim]Running Grab (Auto-Add Max {needed})...[/dim]")
                ctx.invoke(grab, name=None, input_file=input_file, status=False, auto_add=False, auto_add_only=True, max_downloads=needed)
                
            else:
                console.print(f"[yellow]Queue is full ({count} >= {LIMIT}). Skipping replenishment.[/yellow]")
                
        except Exception as e:
            console.print(f"[red]Error during replenishment step: {e}[/red]")
            logger.error(f"Replenish failed: {e}", exc_info=True)

    # 6. Final Stats
    run_step("Step 6/6: Final Library Statistics", stats, query=None, continuity=False, deep=False, verify=False, no_cache=True, no_metadata=False)

    if verbose > 0:
        log_step("Full Update Cycle Complete")
    else:
        console.print(Rule("[bold green]Full Update Cycle Complete[/bold green]"))