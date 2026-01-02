import logging
from typing import Dict, List, Optional
from collections import defaultdict

from .models import Library, Series
from .analysis import semantic_normalize

logger = logging.getLogger(__name__)

class LibraryIndex:
    """
    Indexes the library for fast lookups by ID and Title (synonyms included).
    Acts as the source of truth for series identity.
    """
    def __init__(self):
        self.mal_id_map: Dict[int, Series] = {}
        # Maps normalized title -> List of Series (collisions possible but rare with ID)
        self.title_map: Dict[str, List[Series]] = defaultdict(list)
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
        for name in series.identities:
            norm = semantic_normalize(name)
            if not norm:
                continue
            
            # Avoid adding the same series multiple times to the list for the same normalized key
            if series not in self.title_map[norm]:
                self.title_map[norm].append(series)

    def search(self, query: str) -> List[Series]:
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

    def get_by_id(self, mal_id: int) -> Optional[Series]:
        """Returns a series by MAL ID."""
        if not self.is_built:
            logger.warning("Index lookup called before build.")
            return None
        return self.mal_id_map.get(mal_id)
