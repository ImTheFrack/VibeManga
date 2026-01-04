"""
Duplicate Detection Engines for VibeManga.

Provides three detection strategies:
1. MAL ID Conflicts - High confidence, same MAL ID in different folders
2. Content Duplicates - Medium confidence, same files via hashing/metadata
3. Fuzzy Duplicates - Lower confidence, similar names with AI assistance
"""

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple, Any
from collections import defaultdict

from .models import Library, Series, Volume
from .indexer import LibraryIndex
from .analysis import semantic_normalize, classify_unit
from .constants import SIMILARITY_THRESHOLD

logger = logging.getLogger(__name__)


@dataclass
class DuplicateGroup:
    """Represents a group of duplicate items that should be resolved together."""
    group_id: str
    duplicate_type: str  # 'mal_id', 'content', 'fuzzy'
    confidence: float  # 0.0 to 1.0
    items: List[Any] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.group_id:
            self.group_id = f"{self.duplicate_type}_{id(self)}"


@dataclass
class MALIDDuplicate:
    """Represents duplicate series with the same MAL ID."""
    mal_id: int
    series: List[Series]
    primary_path: Optional[Path] = None


@dataclass
class ContentDuplicate:
    """Represents duplicate files based on content hashing."""
    file_hash: str
    file_size: int
    page_count: Optional[int]
    volumes: List[Volume]
    series_paths: Set[Path] = field(default_factory=set)


class MALIDDuplicateDetector:
    """Detects duplicate series by MAL ID (highest confidence)."""
    
    def __init__(self, library: Library):
        self.library = library
        self.index = LibraryIndex()
        self.index.build(library)
        logger.debug(f"MALIDDuplicateDetector initialized with {self._count_series()} series")
    
    def _count_series(self) -> int:
        """Count total series in library."""
        count = 0
        for main_cat in self.library.categories:
            for sub_cat in main_cat.sub_categories:
                count += len(sub_cat.series)
        return count
    
    def detect(self) -> List[MALIDDuplicate]:
        """Find all MAL ID conflicts in the library."""
        logger.info("=" * 60)
        logger.info("MAL ID DUPLICATE DETECTION STARTED")
        logger.info("=" * 60)

        
        duplicates = []
        processed_mal_ids = set()
        
        # Diagnostic counters
        total_series_scanned = 0
        series_with_mal_id = 0
        unique_mal_ids = set()
        
        # Build our own MAL ID map for debugging - this correctly stores ALL series
        debug_mal_id_map = defaultdict(list)
        
        # First pass: collect all series and their MAL IDs
        logger.debug("Scanning library for series with MAL IDs...")
        for main_cat in self.library.categories:
            for sub_cat in main_cat.sub_categories:
                for series in sub_cat.series:
                    total_series_scanned += 1
                    
                    # FIX: Access MAL ID from metadata (not series.mal_id)
                    mal_id = None
                    if hasattr(series, 'metadata') and series.metadata:
                        mal_id = getattr(series.metadata, 'mal_id', None)
                    
                    logger.debug(f"Series: {series.name}")
                    logger.debug(f"  Path: {series.path}")
                    logger.debug(f"  MAL ID: {mal_id} (type: {type(mal_id)})")
                    logger.debug(f"  Has metadata: {hasattr(series, 'metadata') and series.metadata is not None}")
                    
                    if mal_id:
                        series_with_mal_id += 1
                        unique_mal_ids.add(mal_id)
                        debug_mal_id_map[mal_id].append(series)
                        logger.debug(f"  → Added to MAL ID map: {mal_id}")
                    else:
                        logger.debug(f"  → No MAL ID, skipping")
        
        # Log diagnostic summary
        logger.info(f"DIAGNOSTIC: Scanned {total_series_scanned} series")
        logger.info(f"DIAGNOSTIC: Found {series_with_mal_id} series with MAL IDs")
        logger.info(f"DIAGNOSTIC: Found {len(unique_mal_ids)} unique MAL IDs")
        logger.info(f"DIAGNOSTIC: MAL ID map contains {len(debug_mal_id_map)} entries")
        
        # Log detailed MAL ID map
        logger.debug("Detailed MAL ID map:")
        duplicate_count = 0
        for mal_id, series_list in debug_mal_id_map.items():
            logger.debug(f"  MAL ID {mal_id}: {len(series_list)} series")
            for series in series_list:
                logger.debug(f"    - {series.name} at {series.path}")
            if len(series_list) > 1:
                duplicate_count += 1
        
        logger.info(f"DIAGNOSTIC: Found {duplicate_count} MAL IDs with multiple series")
        
        # FIX: Don't check the index - it overwrites duplicates! Use our debug map instead.
        logger.info("Creating duplicate entries from MAL ID map...")
        
        for mal_id, series_list in debug_mal_id_map.items():
            if mal_id in processed_mal_ids:
                logger.debug(f"Skipping already processed MAL ID: {mal_id}")
                continue
            
            # Skip if only one series has this MAL ID
            if len(series_list) <= 1:
                logger.debug(f"MAL ID {mal_id}: only 1 series, skipping")
                continue
            
            logger.info(f"Found MAL ID conflict: {mal_id} - {len(series_list)} series")
            
            # Create duplicate entry - we already have the full series objects!
            logger.info(f"Creating duplicate entry for MAL ID {mal_id} with {len(series_list)} series")
            duplicates.append(MALIDDuplicate(
                mal_id=mal_id,
                series=series_list  # Use the series list we already built
            ))
            processed_mal_ids.add(mal_id)
        
        # Final summary
        logger.info("=" * 60)
        logger.info(f"MAL ID DETECTION COMPLETE: Found {len(duplicates)} conflicts")
        logger.info("=" * 60)
        
        # Log each found duplicate in detail
        if duplicates:
            logger.info("Detected MAL ID conflicts:")
            for i, dup in enumerate(duplicates, 1):
                logger.info(f"  {i}. MAL ID {dup.mal_id}: {len(dup.series)} series")
                for series in dup.series:
                    logger.info(f"     - {series.name} at {series.path}")
        else:
            logger.info("No MAL ID conflicts detected")
            logger.info("This may indicate:")
            logger.info("  1. No series have MAL IDs assigned")
            logger.info("  2. MAL IDs are unique across all series")
            logger.info("  3. There's a bug in the detection logic (please report!)")
        
        return duplicates
    
    def _find_series_by_path(self, target_path: Path) -> Optional[Series]:
        """Find a series object by its path."""
        logger.debug(f"Searching for series at path: {target_path}")
        for main_cat in self.library.categories:
            for sub_cat in main_cat.sub_categories:
                for series in sub_cat.series:
                    if series.path == target_path:
                        logger.debug(f"  Found match: {series.name}")
                        return series
        logger.warning(f"  Series not found at path: {target_path}")
        return None


class ContentDuplicateDetector:
    """Detects duplicate files by content (hashing or metadata comparison)."""
    
    def __init__(self, library: Library, use_hashing: bool = False):
        self.library = library
        self.use_hashing = use_hashing
    
    def detect(self) -> List[ContentDuplicate]:
        """Find duplicate files across the library."""
        volume_map = defaultdict(list)  # key -> list of volumes
        
        # Collect all volumes from library
        for main_cat in self.library.categories:
            for sub_cat in main_cat.sub_categories:
                for series in sub_cat.series:
                    # Add volumes from series root
                    for vol in series.volumes:
                        key = self._get_volume_key(vol)
                        if key:
                            volume_map[key].append(vol)
                    
                    # Add volumes from subgroups
                    for sg in series.sub_groups:
                        for vol in sg.volumes:
                            key = self._get_volume_key(vol)
                            if key:
                                volume_map[key].append(vol)
        
        # Filter for actual duplicates
        duplicates = []
        for key, volumes in volume_map.items():
            if len(volumes) > 1:
                # Check if they're actually duplicates (not just same size)
                duplicate = ContentDuplicate(
                    file_hash=key,
                    file_size=volumes[0].size_bytes,
                    page_count=volumes[0].page_count,
                    volumes=volumes,
                    series_paths={vol.path.parent for vol in volumes}
                )
                duplicates.append(duplicate)
        
        return duplicates
    
    def _get_volume_key(self, volume: Volume) -> Optional[str]:
        """Generate a key for duplicate detection."""
        if self.use_hashing:
            return self._hash_file(volume.path)
        else:
            # Use size + page count as proxy (faster, good enough for most cases)
            if volume.page_count:
                return f"{volume.size_bytes}_{volume.page_count}"
            return str(volume.size_bytes)
    
    def _hash_file(self, file_path: Path) -> Optional[str]:
        """Generate MD5 hash of file (slow but accurate)."""
        try:
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            logger.warning(f"Failed to hash {file_path}: {e}")
            return None


class FuzzyDuplicateDetector:
    """Detects potential duplicates using fuzzy name matching."""
    
    def __init__(self, library: Library, threshold: float = SIMILARITY_THRESHOLD):
        self.library = library
        self.threshold = threshold
    
    def detect(self) -> List[DuplicateGroup]:
        """Find series with similar names across the library."""
        # Get all series paths and their identities
        series_info = []
        for main_cat in self.library.categories:
            for sub_cat in main_cat.sub_categories:
                for series in sub_cat.series:
                    identities = list(series.identities)
                    if series.path.name not in identities:
                        identities.append(series.path.name)
                    
                    series_info.append({
                        'series': series,
                        'identities': identities,
                        'normalized': [semantic_normalize(name) for name in identities]
                    })
        
        # Find potential duplicates
        duplicates = []
        processed = set()
        
        for i, info1 in enumerate(series_info):
            if id(info1['series']) in processed:
                continue
            
            similar_group = [info1['series']]
            
            for j in range(i + 1, len(series_info)):
                info2 = series_info[j]
                
                # Check if any identities match
                max_similarity = 0
                for norm1 in info1['normalized']:
                    for norm2 in info2['normalized']:
                        if len(norm1) > 3 and len(norm2) > 3:  # Avoid short name matches
                            similarity = self._calculate_similarity(norm1, norm2)
                            max_similarity = max(max_similarity, similarity)
                
                if max_similarity >= self.threshold:
                    similar_group.append(info2['series'])
                    processed.add(id(info2['series']))
            
            if len(similar_group) > 1:
                # Check if they have different MAL IDs (if both have them)
                mal_ids = {s.metadata.mal_id for s in similar_group if s.metadata.mal_id}
                if len(mal_ids) > 1:
                    # Different MAL IDs = likely different series, skip
                    continue
                
                duplicates.append(DuplicateGroup(
                    group_id=f"fuzzy_{id(similar_group[0])}",
                    duplicate_type='fuzzy',
                    confidence=max_similarity,
                    items=similar_group,
                    metadata={'similarity': max_similarity}
                ))
            
            processed.add(id(info1['series']))
        
        return duplicates
    
    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """Calculate similarity ratio between two strings."""
        import difflib
        return difflib.SequenceMatcher(None, str1, str2).ratio()


class DedupeEngine:
    """Main orchestrator for duplicate detection."""
    
    def __init__(self, library: Library, use_hashing: bool = False):
        self.library = library
        self.use_hashing = use_hashing
        self.mal_detector = MALIDDuplicateDetector(library)
        self.content_detector = ContentDuplicateDetector(library, use_hashing)
        self.fuzzy_detector = FuzzyDuplicateDetector(library)
    
    def detect_by_mode(self, mode: str) -> Dict[str, List[Any]]:
        """
        Run only the specified detection mode(s).
        
        Args:
            mode: Detection mode - 'all', 'mal-id', 'content', or 'fuzzy'
            
        Returns:
            Dictionary with duplicate groups for the selected mode(s)
        """
        logger.info("=" * 60)
        logger.info(f"SELECTIVE DUPLICATE DETECTION STARTED (mode={mode})")
        logger.info("=" * 60)
        
        results = {
            'mal_id_conflicts': [],
            'content_duplicates': [],
            'fuzzy_duplicates': []
        }
        
        if mode == 'all':
            # Run all detection modes
            return self.detect_all()
        
        elif mode == 'mal-id':
            # Only run MAL ID detection (fastest)
            logger.info("Running MAL ID conflict detection only...")
            results['mal_id_conflicts'] = self.mal_detector.detect()
            logger.info(f"Detection complete: Found {len(results['mal_id_conflicts'])} MAL ID conflicts")
            
        elif mode == 'content':
            # Only run content duplicate detection
            logger.info("Running content duplicate detection only...")
            results['content_duplicates'] = self.content_detector.detect()
            logger.info(f"Detection complete: Found {len(results['content_duplicates'])} content duplicates")
            
        elif mode == 'fuzzy':
            # Only run fuzzy name detection
            logger.info("Running fuzzy name detection only...")
            results['fuzzy_duplicates'] = self.fuzzy_detector.detect()
            logger.info(f"Detection complete: Found {len(results['fuzzy_duplicates'])} fuzzy matches")
            
        else:
            raise ValueError(f"Unknown detection mode: {mode}")
        
        total_found = sum(len(v) for v in results.values())
        logger.info("=" * 60)
        logger.info(f"DETECTION COMPLETE: {total_found} duplicate groups found (mode={mode})")
        logger.info("=" * 60)
        
        return results
    
    def detect_all(self) -> Dict[str, List[Any]]:
        """Run all detection engines and return results."""
        logger.info("=" * 60)
        logger.info("COMPREHENSIVE DUPLICATE DETECTION STARTED")
        logger.info("=" * 60)
        
        results = {
            'mal_id_conflicts': [],
            'content_duplicates': [],
            'fuzzy_duplicates': []
        }
        
        # Detect MAL ID conflicts (highest priority)
        logger.info("Phase 1: Detecting MAL ID conflicts...")
        results['mal_id_conflicts'] = self.mal_detector.detect()
        logger.info(f"Phase 1 complete: Found {len(results['mal_id_conflicts'])} MAL ID conflicts")
        
        # Detect content duplicates
        logger.info("Phase 2: Detecting content duplicates...")
        results['content_duplicates'] = self.content_detector.detect()
        logger.info(f"Phase 2 complete: Found {len(results['content_duplicates'])} content duplicates")
        
        # Detect fuzzy duplicates
        logger.info("Phase 3: Detecting fuzzy name duplicates...")
        results['fuzzy_duplicates'] = self.fuzzy_detector.detect()
        logger.info(f"Phase 3 complete: Found {len(results['fuzzy_duplicates'])} fuzzy duplicates")
        
        # Final summary
        total_duplicates = sum(len(v) for v in results.values())
        logger.info("=" * 60)
        logger.info(f"DETECTION COMPLETE: {total_duplicates} total duplicate groups found")
        logger.info("=" * 60)
        
        return results
    
    def get_duplicate_summary(self, results: Dict[str, List[Any]]) -> Dict[str, Any]:
        """Generate a summary of duplicate detection results."""
        summary = {
            'total_groups': 0,
            'mal_id_groups': len(results['mal_id_conflicts']),
            'content_groups': len(results['content_duplicates']),
            'fuzzy_groups': len(results['fuzzy_duplicates']),
            'total_affected_series': 0,
            'total_duplicate_files': 0,
            'estimated_space_mb': 0
        }
        
        summary['total_groups'] = summary['mal_id_groups'] + summary['content_groups'] + summary['fuzzy_groups']
        
        # Count affected series and files
        for conflict in results['mal_id_conflicts']:
            summary['total_affected_series'] += len(conflict.series)
        
        for duplicate in results['content_duplicates']:
            summary['total_duplicate_files'] += len(duplicate.volumes)
            # Space calculation: (n-1) * size for n duplicates
            if len(duplicate.volumes) > 1:
                summary['estimated_space_mb'] += (len(duplicate.volumes) - 1) * (duplicate.file_size / (1024 * 1024))
        
        for group in results['fuzzy_duplicates']:
            summary['total_affected_series'] += len(group.items)
        
        return summary