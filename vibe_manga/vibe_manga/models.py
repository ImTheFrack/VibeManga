from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Set
from pathlib import Path

from .constants import BYTES_PER_MB

@dataclass
class SeriesMetadata:
    """Standardized schema for manga metadata.
    saved to series.json in each series folder.
    """
    title: str = "Unknown"
    title_english: Optional[str] = None
    title_japanese: Optional[str] = None
    synonyms: List[str] = field(default_factory=list)
    authors: List[str] = field(default_factory=list)
    synopsis: str = ""
    genres: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    demographics: List[str] = field(default_factory=list)
    status: str = "Unknown" # Completed, Ongoing, Hiatus, Cancelled
    total_volumes: Optional[int] = None
    total_chapters: Optional[int] = None
    release_year: Optional[int] = None
    mal_id: Optional[int] = None
    anilist_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SeriesMetadata':
        # Filter unknown keys to prevent init errors if schema changes
        valid_keys = cls.__annotations__.keys()
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        
        # Handle None values for list fields - use default_factory instead
        list_fields = ['synonyms', 'authors', 'genres', 'tags', 'demographics']
        for field_name in list_fields:
            if field_name in filtered_data and filtered_data[field_name] is None:
                # Remove None values so default_factory will be used
                del filtered_data[field_name]
        
        return cls(**filtered_data)

@dataclass
class Volume:
    """Represents a single manga file (cbz, cbr, etc.)"""
    path: Path
    name: str
    size_bytes: int
    mtime: float = 0.0
    page_count: Optional[int] = None
    is_corrupt: bool = False

    @property
    def size_mb(self) -> float:
        """Returns the size in megabytes."""
        return self.size_bytes / BYTES_PER_MB

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "name": self.name,
            "size_bytes": self.size_bytes,
            "mtime": self.mtime,
            "page_count": self.page_count,
            "is_corrupt": self.is_corrupt
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Volume':
        return cls(
            path=Path(data["path"]),
            name=data["name"],
            size_bytes=data["size_bytes"],
            mtime=data.get("mtime", 0.0),
            page_count=data.get("page_count"),
            is_corrupt=data.get("is_corrupt", False)
        )

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "volumes": [v.to_dict() for v in self.volumes]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SubGroup':
        return cls(
            name=data["name"],
            path=Path(data["path"]),
            volumes=[Volume.from_dict(v) for v in data.get("volumes", [])]
        )

@dataclass
class Series:
    """Represents a specific Manga title (e.g., 'Kaiju No. 8')"""
    name: str
    path: Path
    # Volumes directly in the series folder
    volumes: List[Volume] = field(default_factory=list)
    # Subdirectories that contain volumes (sub-series or groupings)
    sub_groups: List[SubGroup] = field(default_factory=list)
    # External data (e.g. from Nyaa or other sources)
    external_data: Dict[str, Any] = field(default_factory=dict)
    # Metadata (e.g. from MAL/Jikan/AI via series.json)
    metadata: SeriesMetadata = field(default_factory=SeriesMetadata)

    @property
    def identities(self) -> Set[str]:
        """
        Returns a set of all known names/titles for this series.
        Used for fuzzy matching and indexing.
        """
        ids = {self.name}
        if self.metadata.title and self.metadata.title != "Unknown":
            ids.add(self.metadata.title)
        if self.metadata.title_english:
            ids.add(self.metadata.title_english)
        if self.metadata.title_japanese:
            ids.add(self.metadata.title_japanese)
        if self.metadata.synonyms:
            ids.update(self.metadata.synonyms)
        # We don't indiscriminately add tags as identities unless we are sure they are synonyms
        return ids

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "volumes": [v.to_dict() for v in self.volumes],
            "sub_groups": [sg.to_dict() for sg in self.sub_groups],
            "external_data": self.external_data,
            "metadata": self.metadata.to_dict()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Series':
        return cls(
            name=data["name"],
            path=Path(data["path"]),
            volumes=[Volume.from_dict(v) for v in data.get("volumes", [])],
            sub_groups=[SubGroup.from_dict(sg) for sg in data.get("sub_groups", [])],
            external_data=data.get("external_data", {}),
            metadata=SeriesMetadata.from_dict(data.get("metadata", {}))
        )

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "sub_categories": [sc.to_dict() for sc in self.sub_categories],
            "series": [s.to_dict() for s in self.series]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], parent: Optional['Category'] = None) -> 'Category':
        cat = cls(
            name=data["name"],
            path=Path(data["path"]),
            parent=parent
        )
        cat.sub_categories = [cls.from_dict(sc, parent=cat) for sc in data.get("sub_categories", [])]
        cat.series = [Series.from_dict(s) for s in data.get("series", [])]
        return cat

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "categories": [c.to_dict() for c in self.categories]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Library':
        lib = cls(path=Path(data["path"]))
        lib.categories = [Category.from_dict(c) for c in data.get("categories", [])]
        return lib

def _count_subcats(cat: Category) -> int:
    count = len(cat.sub_categories)
    for sub in cat.sub_categories:
        count += _count_subcats(sub)
    return count