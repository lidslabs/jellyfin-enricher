"""Thin Jellyfin API client.

Uses the X-Emby-Token header for authenticated requests. The API key must
have admin scope; the Path field on Items requires metadata management
permissions.

Config is resolved from the DB-effective settings at instance construction
time, so a settings page update takes effect on the next client created.
"""

import logging
import uuid
import httpx

from .config import effective_jellyfin_url, effective_jellyfin_api_key

log = logging.getLogger(__name__)


class JellyfinNotConfiguredError(RuntimeError):
    """Raised when Jellyfin URL or API key is unset (neither env nor DB)."""
    pass


class JellyfinClient:
    def __init__(self) -> None:
        self.base_url = effective_jellyfin_url()
        self.api_key = effective_jellyfin_api_key()
        if not self.base_url or not self.api_key:
            raise JellyfinNotConfiguredError(
                "Jellyfin URL or API key is not set. Configure them in Settings."
            )
        self.client = httpx.Client(
            timeout=30.0,
            headers={"X-Emby-Token": self.api_key},
        )

    def get_items(self, item_type: str) -> list[dict]:
        items: list[dict] = []
        start_index = 0
        page_size = 500
        while True:
            r = self.client.get(
                f"{self.base_url}/Items",
                params={
                    "IncludeItemTypes": item_type,
                    "Recursive": "true",
                    "Fields": "Path,ProductionYear",
                    "StartIndex": start_index,
                    "Limit": page_size,
                },
            )
            r.raise_for_status()
            data = r.json()
            batch = data.get("Items", [])
            items.extend(batch)
            if len(batch) < page_size:
                break
            start_index += page_size
        log.debug("Fetched %d %s items from Jellyfin", len(items), item_type)
        return items

    def get_movies(self) -> list[dict]:
        return self.get_items("Movie")

    def get_series(self) -> list[dict]:
        return self.get_items("Series")

    def fetch_primary_image(self, item_id: str) -> tuple[bytes, str]:
        r = self.client.get(
            f"{self.base_url}/Items/{item_id}/Images/Primary",
            params={"maxWidth": 300, "quality": 85},
        )
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "image/jpeg")

    def system_info(self) -> dict:
        """Used by the settings page Test Connection feature."""
        r = self.client.get(f"{self.base_url}/System/Info")
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "JellyfinClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


# --- standalone auth helper (no admin key required) ---

_CLIENT_AUTH_HEADER = (
    'MediaBrowser Client="JellyfinEnricher", '
    'Device="enricher", DeviceId="jellyfin-enricher", '
    'Version="0.4.0"'
)


def authenticate_user(username: str, password: str) -> dict | None:
    """Validate user credentials against Jellyfin's AuthenticateByName endpoint.

    Returns the User object on success (including the Policy with the
    IsAdministrator flag), None on failure. Uses a fresh httpx client and
    no admin token: this is an unauthenticated call from Jellyfin's view.
    """
    base_url = effective_jellyfin_url()
    if not base_url:
        return None

    headers = {
        "X-Emby-Authorization": _CLIENT_AUTH_HEADER,
        "Content-Type": "application/json",
    }
    body = {"Username": username, "Pw": password}
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                f"{base_url}/Users/AuthenticateByName",
                json=body,
                headers=headers,
            )
            if r.status_code != 200:
                log.info("Jellyfin auth failed for %r: status=%d", username, r.status_code)
                return None
            return r.json().get("User")
    except httpx.HTTPError as e:
        log.warning("Jellyfin auth network error for %r: %s", username, e)
        return None


def test_connection() -> tuple[bool, str]:
    """Returns (ok, message). Used by the Settings page Test button."""
    try:
        with JellyfinClient() as jf:
            info = jf.system_info()
            return True, f"Connected to {info.get('ServerName', 'Jellyfin')} v{info.get('Version', '?')}"
    except JellyfinNotConfiguredError as e:
        return False, str(e)
    except httpx.HTTPStatusError as e:
        return False, f"HTTP {e.response.status_code}: check API key has admin scope"
    except httpx.HTTPError as e:
        return False, f"Connection failed: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"
