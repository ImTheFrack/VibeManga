
import time
import json
from dataclasses import dataclass, asdict
from typing import Optional
from datetime import datetime
from urllib.parse import quote_plus

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
from rich.live import Live
from rich.console import Console, Group
from rich.text import Text

from . import constants as c

console = Console()


@dataclass
class Torrent:
    name: str
    torrent_link: str
    magnet_link: str
    size: str
    date: str
    seeders: int
    leechers: int
    completed: int


def _create_retry_session(
    retries: int = c.SCRAPER_RETRY_COUNT,
    backoff_factor: float = c.SCRAPER_RETRY_BACKOFF_FACTOR,
    status_forcelist: tuple = (500, 502, 503, 504),
) -> requests.Session:
    """Creates a requests session with retry logic."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _parse_row(row) -> Torrent | None:
    """Parses a table row from nyaa.si into a Torrent object."""
    try:
        columns = row.find_all("td")
        if len(columns) < c.NYAA_MIN_COLUMNS:
            return None

        # Column 1 contains the name. It may have multiple 'a' tags, the last one is the title.
        name_cell = columns[c.NYAA_COL_IDX_NAME]
        name_anchor = name_cell.find_all("a")[-1]
        name = name_anchor.get("title", "").strip()

        # Column 2 contains torrent and magnet links
        links_cell = columns[c.NYAA_COL_IDX_LINKS]
        torrent_link = c.NYAA_BASE_URL + links_cell.find("a", href=lambda href: href and ".torrent" in href)["href"]
        magnet_link = links_cell.find("a", href=lambda href: href and "magnet:" in href)["href"]

        return Torrent(
            name=name,
            torrent_link=torrent_link,
            magnet_link=magnet_link,
            size=columns[c.NYAA_COL_IDX_SIZE].text.strip(),
            date=columns[c.NYAA_COL_IDX_DATE].get("data-timestamp"),
            seeders=int(columns[c.NYAA_COL_IDX_SEEDERS].text.strip()),
            leechers=int(columns[c.NYAA_COL_IDX_LEECHERS].text.strip()),
            completed=int(columns[c.NYAA_COL_IDX_COMPLETED].text.strip()),
        )
    except (AttributeError, IndexError, ValueError, TypeError):
        # If any parsing fails (e.g., missing attribute, bad integer conversion), skip this row.
        return None


def scrape_nyaa(
    pages: int = c.NYAA_DEFAULT_PAGES_TO_SCRAPE,
    user_agent: Optional[str] = None,
    stop_at_timestamp: Optional[int] = None,
    query: Optional[str] = None
):
    """
    Scrapes the first N pages of nyaa.si for English-translated literature.

    Args:
        pages: The number of pages to scrape.
        user_agent: An optional user agent string to override the default.
        stop_at_timestamp: If provided, stop scraping when a torrent with this
                           timestamp (or older) is found.
        query: Optional search query.

    Returns:
        A list of dictionaries, where each dictionary represents a torrent.
    """
    all_torrents = []
    
    headers = {"User-Agent": user_agent or c.SCRAPER_USER_AGENT}
    
    session = _create_retry_session()

    # Progress Bar Setup
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
    )
    status_text = Text("Initializing...", style="dim")
    display_group = Group(progress, status_text)

    with Live(display_group, console=console, refresh_per_second=10):
        task_desc = f"[bold cyan]Searching Nyaa for '{query}'..." if query else "[bold cyan]Scraping Nyaa..."
        task_id = progress.add_task(task_desc, total=pages)

        for page_num in range(1, pages + 1):
            if query:
                # Use search template
                url = c.NYAA_SEARCH_URL_TEMPLATE.format(query=quote_plus(query), page=page_num)
            else:
                # Use default template
                url = c.NYAA_ENGLISH_TRANSLATED_URL_TEMPLATE.format(page=page_num)
            
            status_text.plain = f"Fetching Page {page_num}/{pages}: {url}"
            
            try:
                response = session.get(url, headers=headers, timeout=c.SCRAPER_TIMEOUT_SECONDS)
                response.raise_for_status()  # Raise an exception for bad status codes

                soup = BeautifulSoup(response.text, "lxml")
                rows = soup.select(c.NYAA_TORRENT_TABLE_SELECTOR)

                if not rows and query:
                    # If searching and no rows found, we've likely reached the end of results
                    status_text.plain = f"No results on page {page_num}. Stopping."
                    break

                for row in rows:
                    torrent_data = _parse_row(row)
                    if torrent_data:
                        # Check for incremental stop condition
                        if stop_at_timestamp is not None:
                            try:
                                # _parse_row sets date as a string timestamp, convert for comparison
                                t_time = int(torrent_data.date)
                                if t_time <= stop_at_timestamp:
                                    date_str = datetime.fromtimestamp(t_time).strftime('%Y-%m-%d %H:%M:%S')
                                    # Since we are in a Live display, we should print outside or update status
                                    # To be clean, we'll let the function return, and the caller handles the message
                                    # OR we can print a message via console.print (Live will handle it)
                                    console.print(f"[green]Found existing entry from {date_str}, stopping incremental scrape.[/green]")
                                    return all_torrents
                            except (ValueError, TypeError):
                                pass

                        all_torrents.append(asdict(torrent_data))

                # Update progress
                progress.advance(task_id)
                status_text.plain = f"Page {page_num} processed. {len(all_torrents)} total entries found."

                # Rate limit requests
                time.sleep(1 / c.SCRAPER_RATE_LIMIT_PER_SECOND)

            except requests.RequestException as e:
                console.print(f"[red]Error fetching page {page_num}: {e}[/red]")
                continue # Move to the next page

    return all_torrents
def get_latest_timestamp_from_nyaa(user_agent: Optional[str] = None) -> Optional[int]:
    """
    Scrapes the first page of nyaa.si to find the most recent entry's timestamp.

    Args:
        user_agent: An optional user agent string to override the default.

    Returns:
        The highest timestamp found on the page, or None if an error occurs.
    """
    url = c.NYAA_ENGLISH_TRANSLATED_URL_TEMPLATE.format(page=1)
    headers = {"User-Agent": user_agent or c.SCRAPER_USER_AGENT}
    session = _create_retry_session()

    try:
        response = session.get(url, headers=headers, timeout=c.SCRAPER_TIMEOUT_SECONDS)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        rows = soup.select(c.NYAA_TORRENT_TABLE_SELECTOR)
        
        timestamps = []
        for row in rows:
            try:
                timestamp = int(row.find_all("td")[c.NYAA_COL_IDX_DATE].get("data-timestamp"))
                timestamps.append(timestamp)
            except (ValueError, TypeError, AttributeError, IndexError):
                continue
        
        return max(timestamps) if timestamps else None

    except requests.RequestException as e:
        console.print(f"[red]Could not check for updates: {e}[/red]")
        return None

if __name__ == '__main__':
    # For testing the scraper directly
    results = scrape_nyaa(pages=1)
    print(json.dumps(results, indent=2))
