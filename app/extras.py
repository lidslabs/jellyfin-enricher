"""Registry of extras types this enricher can handle.

Adding a new type is a four-step change:
  1. Add the enum member here.
  2. Add an ExtrasDefinition entry below.
  3. Add a *_exists() check in scanner.py for the file convention.
  4. Add a build_command branch in downloader.py for yt-dlp invocation.

Until ui_exposed=True is set, the type stays out of the navigation but
the underlying machinery still works.
"""

from dataclasses import dataclass
from enum import Enum


class ExtrasType(str, Enum):
    THEME = "theme"
    TRAILER = "trailer"
    # Future candidates (not yet wired):
    # BEHIND_THE_SCENES = "behindthescenes"
    # INTERVIEW = "interview"
    # FEATURETTE = "featurette"


@dataclass(frozen=True)
class ExtrasDefinition:
    type: ExtrasType
    label: str
    applies_to: tuple[str, ...]   # Jellyfin item types this extras applies to
    ui_exposed: bool


EXTRAS: dict[ExtrasType, ExtrasDefinition] = {
    ExtrasType.THEME: ExtrasDefinition(
        type=ExtrasType.THEME,
        label="Theme Song",
        applies_to=("Series",),
        ui_exposed=True,
    ),
    ExtrasType.TRAILER: ExtrasDefinition(
        type=ExtrasType.TRAILER,
        label="Trailer",
        applies_to=("Movie",),
        ui_exposed=True,
    ),
}


def ui_exposed_extras() -> list[ExtrasDefinition]:
    return [e for e in EXTRAS.values() if e.ui_exposed]
