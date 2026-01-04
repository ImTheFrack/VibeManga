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

import re
from typing import List, Set, Dict

from .base import console, get_library_root, run_scan_with_progress
from ..constants import (
    NYAA_DEFAULT_PAGES_TO_SCRAPE,
    NYAA_DEFAULT_OUTPUT_FILENAME,
    SCRAPE_HISTORY_FILENAME,
    SCRAPE_QUERY_COOLDOWN_DAYS
)
from ..nyaa_scraper import scrape_nyaa, get_latest_timestamp_from_nyaa
from ..logging import get_logger, log_substep
from ..analysis import find_gaps

logger = get_logger(__name__)

# Minimal set of stop words for search query generation
# We avoid the full STOP_WORDS list because it includes numbers and common words 
# that are significant in titles (e.g. "Zero", "New", "One").
SEARCH_STOP_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'on', 'at', 'by', 
    'for', 'with', 'from', 's', 'is', 'that', 'this', 'are', 'was', 'be'
}

def load_query_history() -> Dict[str, float]:
    """Loads the history of scraped queries and their timestamps."""
    if os.path.exists(SCRAPE_HISTORY_FILENAME):
        try:
            with open(SCRAPE_HISTORY_FILENAME, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not load scrape history from '{SCRAPE_HISTORY_FILENAME}': {e}. Starting fresh.")
    return {}

def save_query_history(history: Dict[str, float]) -> None:
    """Saves the history of scraped queries."""
    try:
        with open(SCRAPE_HISTORY_FILENAME, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2)
    except IOError as e:
        logger.error(f"Error saving scrape history to '{SCRAPE_HISTORY_FILENAME}': {e}")

def generate_search_alternatives(query: str) -> List[str]:
    """
    Generates alternative search queries based on the input query.
    1. Original query
    2. Sanitized (replace special chars with space)
    3. Keywords only (remove minimal stop words)
    4. First 2 keywords (if applicable)
    """
    if not query:
        return []
        
    alternatives = []
    
    # 1. Original
    alternatives.append(query)
    
    # 2. Sanitized (replace special chars with space)
    # e.g. "Re:Zero" -> "Re Zero"
    # Keep alphanumeric and spaces.
    sanitized = "".join([c if c.isalnum() else " " for c in query]).strip()
    sanitized = " ".join(sanitized.split()) # Collapse spaces
    if sanitized and sanitized.lower() != query.lower():
        alternatives.append(sanitized)
        
    # 3. Keywords Only (Remove stop words from sanitized version)
    words = sanitized.split()
    keywords = [w for w in words if w.lower() not in SEARCH_STOP_WORDS]
    
    if not keywords:
        return alternatives

    keywords_str = " ".join(keywords)
    # Only add if distinct and not too short (unless original was short)
    if (keywords_str and 
        keywords_str.lower() != sanitized.lower() and 
        keywords_str.lower() != query.lower()):
        
        # Safety check: Don't suggest extremely short alternatives 
        # that weren't in the original query, to avoid spamming "Re" or "To".
        # If the generated keyword string is < 3 chars, only allow it if the original query was also < 4.
        if len(keywords_str) >= 3 or len(query) < 4:
            alternatives.append(keywords_str)
        
    # 4. First 2 Keywords (if we have more than 2)
    # Useful for long titles where the end might vary or have typos
    if len(keywords) > 2:
        first_two = " ".join(keywords[:2])
        if (first_two.lower() != keywords_str.lower() and 
            (len(first_two) >= 3 or len(query) < 4)):
             alternatives.append(first_two)

    # Dedup preserving order
    seen = set()
    unique_alts = []
    for alt in alternatives:
        # Check case-insensitive uniqueness but keep original casing
        key = alt.lower()
        if key not in seen:
            seen.add(key)
            unique_alts.append(alt)
            
    return unique_alts

@click.command()
@click.option("--pages", default=NYAA_DEFAULT_PAGES_TO_SCRAPE, help="Number of pages to scrape.")
@click.option("--output", default=NYAA_DEFAULT_OUTPUT_FILENAME, help="Output file to save JSON results.")
@click.option("--user-agent", help="Override the default User-Agent for scraping.")
@click.option("--force", is_flag=True, help="Force a full rescrape, ignoring existing data.")
@click.option("--summarize", is_flag=True, help="Display a summary of the scraped data.")
@click.option("--query", "-q", help="Search query to filter results.")
@click.option("--continuity", is_flag=True, help="Scan library and scrape for series with missing volumes/chapters.")
def scrape(pages: int, output: str, user_agent: Optional[str], force: bool, summarize: bool, query: Optional[str], continuity: bool) -> None:
    """Scrapes nyaa.si for the latest English-translated literature."""
    logger.info(f"Scrape command started (pages={pages}, output={output}, force={force}, summarize={summarize}, query={query}, continuity={continuity})")

    existing_data = []
    latest_known_timestamp = None
    perform_scrape = True
    
    # Load query history
    query_history = load_query_history()
    now_ts = datetime.datetime.now().timestamp()
    cooldown_seconds = SCRAPE_QUERY_COOLDOWN_DAYS * 24 * 3600

    # 1. Load existing data & Check incremental
    if os.path.exists(output):
        try:
            with open(output, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            if existing_data:
                # Assuming data is list of dicts with 'date' field
                latest_known_timestamp = max(int(entry.get('date', 0)) for entry in existing_data)
                
                if not force and not query and not continuity:
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
        queries_to_try = []
        
        # Add manual query
        if query:
            queries_to_try.extend(generate_search_alternatives(query))
        
        # Add continuity queries
        if continuity:
            root = get_library_root()
            library = run_scan_with_progress(root, "[bold green]Scanning Library for Continuity Checks...")
            
            # Flatten library to get all series
            all_series = []
            for cat in library.categories:
                for sub in cat.sub_categories:
                    all_series.extend(sub.series)
            
            # Identify gaps
            continuity_targets = []
            with console.status("[bold blue]Analyzing continuity gaps..."):
                for s in all_series:
                    if find_gaps(s):
                        # Use metadata title if available for better search results, else folder name
                        # Metadata is populated during scan_library
                        name = s.metadata.title_english or s.metadata.title
                        if not name or name == "Unknown":
                            name = s.name
                        continuity_targets.append(name)
            
            if continuity_targets:
                console.print(f"[green]Found {len(continuity_targets)} series with continuity gaps. Adding to scrape queue.[/green]")
                for target in continuity_targets:
                     queries_to_try.extend(generate_search_alternatives(target))
            else:
                console.print("[green]No continuity gaps found in library.[/green]")

        # Default fallback: If no specific queries, scrape the front page (incremental)
        if not queries_to_try:
             queries_to_try.append(None) 

        new_results = []
        seen_magnets = set(entry.get('magnet_link') for entry in existing_data)
        history_updated = False

        # Dedup queries while preserving order
        unique_queries = []
        seen_q = set()
        for q in queries_to_try:
            # Handle None (default scrape) separately
            if q is None:
                if None not in seen_q:
                    unique_queries.append(None)
                    seen_q.add(None)
                continue
                
            q_norm = q.lower().strip()
            if q_norm not in seen_q:
                unique_queries.append(q)
                seen_q.add(q_norm)
        
        queries_to_try = unique_queries

        for q in queries_to_try:
            if q:
                # Check history cooldown
                last_run = query_history.get(q, 0)
                if not force and (now_ts - last_run < cooldown_seconds):
                    days_ago = (now_ts - last_run) / (24 * 3600)
                    logger.info(f"Skipping query '{q}': Run {days_ago:.1f} days ago (Cooldown: {SCRAPE_QUERY_COOLDOWN_DAYS} days). Use --force to override.")
                    continue
                    
                logger.info(f"Searching for: '{q}'")
            
            # If we are searching, we usually don't want to stop at timestamp unless explicitly asked?
            # But the user might want to scrape *new* results for a query.
            # However, search results aren't strictly chronological if Nyaa sorts by relevance?
            # Nyaa default sort is Date Descending. So timestamp check is valid.
            # But if we search, we might be looking for older stuff too.
            # If query is present, maybe ignore stop_at_timestamp unless force is NOT set?
            # The logic above sets stop_at_timestamp only if not force AND not query (modified logic).
            # Wait, I changed the logic above to: if not force and not query.
            # So if query is present, latest_known_timestamp is ignored (it's None passed to scrape_nyaa).
            # This makes sense for search: find everything matching, up to 'pages'.
            
            # Determine stop condition:
            # If searching (q is not None), ignore timestamp (get all matches up to N pages).
            # If scraping front page (q is None), use timestamp (incremental).
            ts_stop = latest_known_timestamp if (q is None and not force) else None

            results = scrape_nyaa(
                pages=pages,
                user_agent=user_agent,
                stop_at_timestamp=ts_stop,
                query=q
            )
            
            if q:
                # Update history only if search was actually performed
                query_history[q] = now_ts
                history_updated = True
            
            for res in results:
                # Use asdict if it's a dataclass, but scrape_nyaa returns list of dicts (from asdict)
                # scrape_nyaa returns list of dicts.
                magnet = res.get('magnet_link')
                if magnet and magnet not in seen_magnets:
                    new_results.append(res)
                    seen_magnets.add(magnet)
        
        if history_updated:
            save_query_history(query_history)
            
        if new_results:
            # Merge results: New + Old
            combined_data = new_results + existing_data
            
            # Ensure uniqueness (already checked new against old, but good to be safe)
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
