"""
Scrape command for VibeManga CLI.

Scrapes Nyaa.si for the latest English-translated literature.
"""
import os
import json
import datetime
import click
import logging
from typing import Optional
from rich.table import Table
from rich import box

from .base import console
from ..constants import (
    NYAA_DEFAULT_PAGES_TO_SCRAPE,
    NYAA_DEFAULT_OUTPUT_FILENAME
)
from ..nyaa_scraper import scrape_nyaa, get_latest_timestamp_from_nyaa
from ..logging import get_logger, log_substep

logger = get_logger(__name__)

@click.command()
@click.option("--pages", default=NYAA_DEFAULT_PAGES_TO_SCRAPE, help="Number of pages to scrape.")
@click.option("--output", default=NYAA_DEFAULT_OUTPUT_FILENAME, help="Output file to save JSON results.")
@click.option("--user-agent", help="Override the default User-Agent for scraping.")
@click.option("--force", is_flag=True, help="Force a full rescrape, ignoring existing data.")
@click.option("--summarize", is_flag=True, help="Display a summary of the scraped data.")
def scrape(pages: int, output: str, user_agent: Optional[str], force: bool, summarize: bool) -> None:
    """Scrapes nyaa.si for the latest English-translated literature."""
    logger.info(f"Scrape command started (pages={pages}, output={output}, force={force}, summarize={summarize})")

    existing_data = []
    latest_known_timestamp = None
    perform_scrape = True

    # 1. Load existing data & Check incremental
    if os.path.exists(output):
        try:
            with open(output, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            if existing_data:
                # Assuming data is list of dicts with 'date' field
                latest_known_timestamp = max(int(entry.get('date', 0)) for entry in existing_data)
                
                if not force:
                    date_str = datetime.datetime.fromtimestamp(latest_known_timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    logger.info(f"Incremental scrape active. Stopping at timestamp: {latest_known_timestamp} ({date_str})")
                    
                    # Quick check against live site
                    latest_live_timestamp = get_latest_timestamp_from_nyaa(user_agent=user_agent)
                    if latest_live_timestamp and latest_live_timestamp <= latest_known_timestamp:
                        logger.info("The Nyaa index has not been updated since the last scrape. Use --force to override.")
                        perform_scrape = False
                        
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Could not parse existing file '{output}': {e}. Starting fresh.")
            # If parse failed, treat as if no existing data
            existing_data = []

    # 2. Perform Scrape (if needed)
    if perform_scrape:
        new_results = scrape_nyaa(
            pages=pages,
            user_agent=user_agent,
            stop_at_timestamp=latest_known_timestamp if not force else None
        )

        if new_results:
            # Merge results: New + Old
            combined_data = new_results + existing_data
            
            # Ensure uniqueness
            unique_data = {v['magnet_link']: v for v in combined_data}.values()
            # Sort by date descending
            final_list = sorted(unique_data, key=lambda x: int(x.get('date', 0)), reverse=True)

            # Save
            try:
                with open(output, 'w', encoding='utf-8') as f:
                    json.dump(final_list, f, indent=2)
                
                logger.info(f"Successfully saved {len(final_list)} results ({len(new_results)} new) to {output}")
                log_substep(f"Saved {len(final_list)} total entries ({len(new_results)} new) to {output}")
                
                # Update in-memory data for summary
                existing_data = final_list
                
            except IOError as e:
                logger.error(f"Error writing to output file {output}: {e}", exc_info=True)
                
            logger.info(f"Scrape command completed. Found {len(new_results)} new entries.")
        else:
            if not existing_data and perform_scrape:
                 logger.warning("Scraping completed with no results.")
            elif perform_scrape:
                 logger.info("No new entries found. Library is up to date.")

    # 3. Summarize
    if summarize:
        if not existing_data:
            console.print("[yellow]No data to summarize.[/yellow]")
        else:
            table = Table(title=f"Scrape Summary: {output}", box=box.SIMPLE)
            table.add_column("Date", style="cyan", no_wrap=True)
            table.add_column("Name", style="white")
            table.add_column("Size", style="green", justify="right")

            for entry in existing_data:
                try:
                    ts = int(entry.get('date', 0))
                    date_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
                except ValueError:
                    date_str = "Unknown"
                
                table.add_row(
                    date_str,
                    entry.get('name', 'Unknown'),
                    entry.get('size', '?')
                )
            
            console.print(table)
