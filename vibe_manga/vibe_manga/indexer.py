import logging
import difflib
import re
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass
from collections import defaultdict

from .models import Library, Series
from .analysis import semantic_normalize
from .constants import SERIES_ALIASES

logger = logging.getLogger(__name__)

@dataclass
class LightweightSeries:
    """Minimal series representation for worker processes."""
    name: str
    path: str
    mal_id: Optional[int] = None

class LibraryIndex:
    """
    Indexes the library for fast lookups by ID and Title (synonyms included).
    Acts as the source of truth for series identity.
    """
    def __init__(self):
        self.mal_id_map: Dict[int, Union[Series, LightweightSeries]] = {}
        # Maps normalized title -> List of Series (collisions possible but rare with ID)
        self.title_map: Dict[str, List[Union[Series, LightweightSeries]]] = defaultdict(list)
        self.is_built: bool = False

    def build(self, library: Library):
        """Iterates the library and populates the index."""
        logger.debug("Building Library Index...")
        self.mal_id_map.clear()
        self.title_map.clear()

        # Recurse through all categories
        for category in library.categories:
            self._index_category(category)
        
        self.is_built = True
        logger.info(f"Library Index built. Indexed {len(self.mal_id_map)} IDs and {len(self.title_map)} distinct title keys.")

    def to_lightweight(self) -> 'LibraryIndex':
        """
        Creates a lightweight copy of the index suitable for pickling/multiprocessing.
        Replaces heavy Series objects with LightweightSeries.
        """
        light_index = LibraryIndex()
        
        # 1. Convert MAL ID Map
        for mal_id, series in self.mal_id_map.items():
            light_series = LightweightSeries(
                name=series.name,
                path=str(series.path),
                mal_id=getattr(series.metadata, 'mal_id', None) if hasattr(series, 'metadata') else series.mal_id
            )
            light_index.mal_id_map[mal_id] = light_series

        # 2. Convert Title Map
        # We need to map original Series objects to their Lightweight counterparts 
        # to maintain reference identity if that mattered (it doesn't really for matching)
        # But efficiently, we can just recreate them.
        
        for norm_title, series_list in self.title_map.items():
            new_list = []
            for series in series_list:
                # Check if we already created a lightweight version in the ID map to save memory?
                # Probably overkill. Just create new simple objects.
                
                # Handle case where series is already lightweight (if re-converting)
                if isinstance(series, LightweightSeries):
                    new_list.append(series)
                else:
                    new_list.append(LightweightSeries(
                        name=series.name,
                        path=str(series.path),
                        mal_id=series.metadata.mal_id
                    ))
            light_index.title_map[norm_title] = new_list
            
        light_index.is_built = True
        return light_index

    def _index_category(self, category):
        """Recursively indexes categories."""
        for series in category.series:
            self._index_series(series)
        
        for sub in category.sub_categories:
            self._index_category(sub)

    def _index_series(self, series: Series):
        """Indexes a single series."""
        # Index by MAL ID
        if series.metadata.mal_id:
            # Conflict check: If two folders claim the same MAL ID, we log a warning.
            if series.metadata.mal_id in self.mal_id_map:
                existing = self.mal_id_map[series.metadata.mal_id]
                logger.warning(f"Duplicate MAL ID {series.metadata.mal_id} detected! '{existing.name}' vs '{series.name}'.")
            
            self.mal_id_map[series.metadata.mal_id] = series

        # Index by Identities (Title, Synonyms, Folder Name)
        # Combine folder identity with global aliases
        identities = list(series.identities)
        if series.name in SERIES_ALIASES:
            identities.extend(SERIES_ALIASES[series.name])

        for name in identities:
            norm = semantic_normalize(name)
            if not norm:
                continue
            
            # Avoid adding the same series multiple times to the list for the same normalized key
            if series not in self.title_map[norm]:
                self.title_map[norm].append(series)

    def search(self, query: str) -> List[Union[Series, LightweightSeries]]:
        """
        Searches for a series by exact normalized title match.
        Returns a list of matches (usually 1, but duplicates possible).
        """
        if not self.is_built:
            logger.warning("Search called before index is built.")
            return []
            
        norm = semantic_normalize(query)
        if not norm:
            return []
            
        return self.title_map.get(norm, [])

    def fuzzy_search(self, query: str, threshold: float = 0.8) -> List[Union[Series, LightweightSeries]]:
        """
        Searches for a series using fuzzy string matching against indexed titles.
        O(N) where N is the number of unique title strings in the library.
        """
        if not self.is_built:
            logger.warning("Fuzzy search called before index is built.")
            return []

        norm_query = semantic_normalize(query)
        if not norm_query:
            return []

        best_match = None
        best_ratio = 0.0
        
        # Iterate unique keys (much faster than iterating all series objects)
        for indexed_title in self.title_map.keys():
            ratio = difflib.SequenceMatcher(None, norm_query, indexed_title).ratio()
            
            if ratio > best_ratio:
                # Enforce number consistency for high-confidence matches
                if ratio >= threshold:
                    nums_a = [int(n) for n in re.findall(r'\d+', norm_query)]
                    nums_b = [int(n) for n in re.findall(r'\d+', indexed_title)]
                    if nums_a != nums_b:
                        continue
                
                best_ratio = ratio
                if ratio >= threshold:
                    best_match = self.title_map[indexed_title]

        if best_match and best_ratio >= threshold:
            # Return all series associated with this key (usually just one)
            return best_match
            
        return []

    def get_by_id(self, mal_id: int) -> Optional[Union[Series, LightweightSeries]]:
        """Returns a series by MAL ID."""
        if not self.is_built:
            logger.warning("Index lookup called before build.")
            return None
        return self.mal_id_map.get(mal_id)
