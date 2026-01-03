import click
from dotenv import load_dotenv, find_dotenv

# Load environment variables immediately
load_dotenv(find_dotenv())

from .ai_api import tracker
from .logging import setup_logging, get_logger, log_substep

# Initialize global logging
setup_logging()
logger = get_logger(__name__)

# CLI Imports
from .cli.base import (
    console,
    get_library_root,
    run_scan_with_progress,
    perform_deep_analysis,
)
from .cli.metadata import metadata
from .cli.hydrate import hydrate
from .cli.rename import rename
from .cli.categorize import categorize
from .cli.organize import organize
from .cli.pullcomplete import pullcomplete
from .cli.scrape import scrape
from .cli.match import match
from .cli.grab import grab
from .cli.pull import pull
from .cli.tree import tree
from .cli.show import show
from .cli.dedupe import dedupe
from .cli.stats import stats

@click.group()
def cli():
    """VibeManga: A CLI for managing your manga collection."""
    pass

cli.add_command(scrape)
cli.add_command(match)
cli.add_command(grab)
cli.add_command(pull)
cli.add_command(tree)
cli.add_command(show)
cli.add_command(dedupe)
cli.add_command(stats)
cli.add_command(metadata)
cli.add_command(hydrate)
cli.add_command(rename)
cli.add_command(categorize)
cli.add_command(organize)
cli.add_command(pullcomplete)

if __name__ == "__main__":
    cli()
