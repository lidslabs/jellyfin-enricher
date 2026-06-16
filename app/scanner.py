"""Scan logic: find Jellyfin items missing a given extras file.

Source of truth for "has the extras" is the filesystem (not the Jellyfin
metadata cache), since Jellyfin only re-detects extras on rescan.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .config import translate_path
from .db import get_permanent_skip_ids
from .extras import ExtrasType
from .jellyfin import JellyfinClient

log = logging.getLogger(__name__)

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".aac"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}


@dataclass
class MediaItem:
    jellyfin_id: str
    title: str
    year: int | None
    item_type: str            # "Movie" or "Series"
    jellyfin_path: str        # path as Jellyfin reports it
    container_path: Path      # translated, what this container sees
    path_accessible: bool     # whether container_path exists at all
    permanently_skipped: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def display_title(self) -> str:
        return f"{self.title} ({self.year})" if self.year else self.title


# --- existence checks ---

def _theme_exists(show_path: Path) -> bool:
    """Jellyfin theme convention: theme.{ext} in the show root directory."""
    if not show_path.is_dir():
        return False
    for child in show_path.iterdir():
        if (
            child.is_file()
            and child.stem.lower() == "theme"
            and child.suffix.lower() in AUDIO_EXTS
        ):
            return True
    return False


def _trailer_exists(movie_file: Path) -> bool:
    """Trailer convention: '<MovieName> (Year)-trailer.<ext>' next to the movie file.

    Also recognizes the 'trailers/' subfolder form for completeness, since
    Jellyfin treats both as valid.
    """
    if movie_file == Path("."):
        return False
    parent = movie_file.parent
    if not parent.is_dir():
        return False
    # Sibling -trailer.* file
    for child in parent.iterdir():
        if (
            child.is_file()
            and child.stem.lower().endswith("-trailer")
            and child.suffix.lower() in VIDEO_EXTS
        ):
            return True
    # trailers/ subfolder
    trailers_dir = parent / "trailers"
    if trailers_dir.is_dir():
        for child in trailers_dir.iterdir():
            if child.is_file() and child.suffix.lower() in VIDEO_EXTS:
                return True
    return False


# --- scan entry point ---

def scan_missing(extras_type: ExtrasType) -> list[MediaItem]:
    """Return all media items missing the given extras type.

    Permanently-skipped items are included but flagged; session skips
    are applied by the route layer, not here.
    """
    with JellyfinClient() as jf:
        if extras_type == ExtrasType.THEME:
            jf_items = jf.get_series()
            item_type = "Series"
            check_fn = _theme_exists
        elif extras_type == ExtrasType.TRAILER:
            jf_items = jf.get_movies()
            item_type = "Movie"
            check_fn = _trailer_exists
        else:
            raise ValueError(f"Unsupported extras type: {extras_type}")

    permanent_ids = get_permanent_skip_ids(extras_type.value)

    out: list[MediaItem] = []
    for jf_item in jf_items:
        jf_path = jf_item.get("Path")
        if not jf_path:
            continue
        container_path = translate_path(jf_path)

        # For movies, Jellyfin reports the file path; for series, the directory.
        # The check function knows which it expects.
        path_accessible = container_path.exists()
        if path_accessible and check_fn(container_path):
            continue  # already has the extras

        jellyfin_id = jf_item["Id"]
        item = MediaItem(
            jellyfin_id=jellyfin_id,
            title=jf_item.get("Name", "Unknown"),
            year=jf_item.get("ProductionYear"),
            item_type=item_type,
            jellyfin_path=jf_path,
            container_path=container_path,
            path_accessible=path_accessible,
            permanently_skipped=(jellyfin_id in permanent_ids),
        )
        if not path_accessible:
            item.notes.append(
                "Path not accessible inside container. "
                "Check volume mounts or PATH_MAPPINGS."
            )
        out.append(item)

    out.sort(key=lambda i: (i.title.lower(), i.year or 0))
    return out
