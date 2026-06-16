"""Application configuration.

All settings come from environment variables. The container expects
the same media paths as Jellyfin sees by default; if your mounts differ,
configure PATH_MAPPINGS to translate Jellyfin-reported paths to local paths.
"""

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Jellyfin (env values are bootstrap defaults; runtime settings live in DB) ---
    jellyfin_url: str = Field("", description="Jellyfin base URL, e.g. http://jellyfin:8096")
    jellyfin_api_key: str = Field("", description="Jellyfin API key (admin scope)")

    # --- Auth (session-based) ---
    enricher_user: str = Field(..., description="Login username")
    enricher_password: str = Field(..., description="Login password")
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(64))"
    session_secret: str = Field(..., description="Secret key for signing session cookies")
    session_max_age: int = 60 * 60 * 24 * 7  # 7 days
    # Set true when serving behind TLS (e.g., BunkerWeb). Cookies will then refuse
    # to transmit over plain HTTP, which would break local 127.0.0.1 access.
    session_https_only: bool = False

    # --- Storage ---
    data_dir: Path = Path("/var/lib/enricher")

    # --- Logging ---
    log_level: str = "INFO"

    # --- Path translation ---
    # Format: "jellyfin_prefix:container_prefix,jellyfin_prefix:container_prefix"
    # Example: "/mnt/movies:/media/movies" rewrites Jellyfin's /mnt/movies/... to
    # /media/movies/... when the enricher checks file existence and writes output.
    # Leave empty if the enricher mounts everything at the same path as Jellyfin.
    path_mappings: str = ""

    # --- Login splash background ---
    # Drop splash.jpg, splash.png, or splash.webp into the data directory and
    # it will be served as the login page background automatically.
    # Overlay opacity controls how dark the layer over the image is (0-1).
    # Splash blur is a CSS backdrop-filter value (e.g., "4px" or "" for none).
    splash_overlay_opacity: float = 0.65
    splash_blur: str = ""

    # --- yt-dlp ---
    trailer_max_height: int = 1080
    theme_audio_format: str = "mp3"  # mp3, flac, m4a, opus, etc.
    theme_audio_quality: str = "0"   # 0 = best (VBR scale for mp3)
    ytdlp_cookies_file: str = ""     # Optional. Inside container, e.g. /data/cookies.txt
    ytdlp_extra_args: str = ""       # Whitespace-separated additional yt-dlp args
    # TLS/JA3 fingerprint impersonation target. Set to empty string to disable.
    # Valid targets: chrome, firefox, safari, edge, and version-specific like
    # chrome-124, safari-17_0. The bare "chrome" alias resolves to a recent
    # Chrome target curl_cffi knows about. Requires curl_cffi installed.
    ytdlp_impersonate: str = "chrome"


settings = Settings()


def translate_path(jellyfin_path: str) -> Path:
    """Convert a Jellyfin-reported path into the path visible inside this container.

    If no mapping matches, returns the path unchanged.
    """
    if not settings.path_mappings:
        return Path(jellyfin_path)
    for mapping in settings.path_mappings.split(","):
        mapping = mapping.strip()
        if ":" not in mapping:
            continue
        jf_prefix, container_prefix = mapping.split(":", 1)
        if jellyfin_path.startswith(jf_prefix):
            return Path(container_prefix + jellyfin_path[len(jf_prefix):])
    return Path(jellyfin_path)


def effective_jellyfin_url() -> str:
    """DB setting wins; env value is the bootstrap fallback."""
    from .db import get_setting
    db_value = get_setting("jellyfin_url")
    return (db_value or settings.jellyfin_url or "").rstrip("/")


def effective_jellyfin_api_key() -> str:
    from .db import get_setting
    db_value = get_setting("jellyfin_api_key")
    return db_value or settings.jellyfin_api_key or ""


def jellyfin_configured() -> bool:
    return bool(effective_jellyfin_url() and effective_jellyfin_api_key())
