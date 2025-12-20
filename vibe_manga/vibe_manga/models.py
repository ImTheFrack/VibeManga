from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path

from .constants import BYTES_PER_MB

@dataclass
class Volume:
    """Represents a single manga file (cbz, cbr, etc.)"""
    path: Path
    name: str
    size_bytes: int
    page_count: Optional[int] = None
    is_corrupt: bool = False

    @property
    def size_mb(self) -> float:
        """Returns the size in megabytes."""
        return self.size_bytes / BYTES_PER_MB

@dataclass
class SubGroup:
    """Represents a subdirectory within a Series (e.g., 'v01-v12' or 'Side Story')"""
    name: str
    path: Path
    volumes: List[Volume] = field(default_factory=list)

    @property
    def total_size_bytes(self) -> int:
        return sum(v.size_bytes for v in self.volumes)

    @property
    def volume_count(self) -> int:
        return len(self.volumes)

    @property
    def total_page_count(self) -> int:
        return sum(v.page_count for v in self.volumes if v.page_count)

@dataclass
class Series:
    """Represents a specific Manga title (e.g., 'Kaiju No. 8')"""
    name: str
    path: Path
    # Volumes directly in the series folder
    volumes: List[Volume] = field(default_factory=list)
    # Subdirectories that contain volumes (sub-series or groupings)
    sub_groups: List[SubGroup] = field(default_factory=list)

    @property
    def total_volume_count(self) -> int:
        return len(self.volumes) + sum(sg.volume_count for sg in self.sub_groups)

    @property
    def total_size_bytes(self) -> int:
        return sum(v.size_bytes for v in self.volumes) + sum(sg.total_size_bytes for sg in self.sub_groups)

    @property
    def total_page_count(self) -> int:
        return sum(v.page_count for v in self.volumes if v.page_count) + \
               sum(sg.total_page_count for sg in self.sub_groups)

    @property
    def is_complex(self) -> bool:
        """True if the series has sub-groups."""
        return len(self.sub_groups) > 0

@dataclass
class Category:
    """Represents a Category (Main or Sub)"""
    name: str
    path: Path
    sub_categories: List['Category'] = field(default_factory=list)
    series: List[Series] = field(default_factory=list)
    parent: Optional['Category'] = None

    @property
    def total_series_count(self) -> int:
        count = len(self.series)
        for sub in self.sub_categories:
            count += sub.total_series_count
        return count

    @property
    def total_volume_count(self) -> int:
        count = sum(s.total_volume_count for s in self.series)
        for sub in self.sub_categories:
            count += sub.total_volume_count
        return count
    
    @property
    def total_size_bytes(self) -> int:
        size = sum(s.total_size_bytes for s in self.series)
        for sub in self.sub_categories:
            size += sub.total_size_bytes
        return size

    @property
    def total_page_count(self) -> int:
        count = sum(s.total_page_count for s in self.series)
        for sub in self.sub_categories:
            count += sub.total_page_count
        return count

@dataclass
class Library:
    """The root of the manga collection"""
    path: Path
    categories: List[Category] = field(default_factory=list)

    @property
    def total_categories(self) -> int:
        # Counts both main and sub categories
        count = 0
        for cat in self.categories:
            count += 1
            count += _count_subcats(cat)
        return count
    
    @property
    def total_series(self) -> int:
        return sum(c.total_series_count for c in self.categories)

    @property
    def total_volumes(self) -> int:
        return sum(c.total_volume_count for c in self.categories)

    @property
    def total_size_bytes(self) -> int:
        return sum(c.total_size_bytes for c in self.categories)

    @property
    def total_pages(self) -> int:
        return sum(c.total_page_count for c in self.categories)

def _count_subcats(cat: Category) -> int:
    count = len(cat.sub_categories)
    for sub in cat.sub_categories:
        count += _count_subcats(sub)
    return count
