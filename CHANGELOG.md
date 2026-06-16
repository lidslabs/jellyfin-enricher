# Changelog

All notable changes to lidslabs/jellyfin-enricher.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: standard semver.

## [0.1.0] - 2026-06-16

First tagged release. Migrated from local-only Docker Compose build to
git-tagged ghcr.io publishing.

### Added
- FastAPI + Jinja2 + HTMX web app for identifying and backfilling missing
  theme songs (TV shows) and trailers (movies) in a Jellyfin library
- yt-dlp-driven downloads with bundled Deno JS runtime for YouTube
  format extraction
- Session-based authentication with form login (replaces HTTP Basic)
- Jellyfin SSO login (admin users only)
- Runtime-configurable Jellyfin URL and API key via settings page
- Login page splash background support (drop splash.{jpg,png,webp} in
  the data directory)
- Extensible extras registry; themes and trailers exposed initially

### Pinned to
- Python 3.12-slim base image
- yt-dlp 2026.06.09
- Deno v2.8.3
- FastAPI 0.115.6, Uvicorn 0.34.0, Jinja2 3.1.5
