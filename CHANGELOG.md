# Changelog

All notable changes to lidslabs/jellyfin-enricher.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: standard semver. Each entry leads with a prose summary and an
optional `### Highlights` block; CI extracts those into the GitHub release notes.

## [Unreleased]

## [0.1.1] - 2026-06-22

Reliability and release-infrastructure release. Fixes YouTube downloads that
were failing because yt-dlp's Chrome impersonation was unavailable, and adds a
CI smoke test that gates publishing on that capability.

### Highlights
- **Fixed broken YouTube downloads.** yt-dlp is now installed with the
  `[default,curl-cffi]` extras so `--impersonate chrome` works — `[default]`
  alone does not pull `curl_cffi`.
- **CI now gates publishing on a smoke test:** `curl_cffi` imports, the Chrome
  impersonate target is available, and Deno is present, all verified before the
  image is pushed.

### Fixed
- yt-dlp `--impersonate chrome` failed at YoutubeDL init with
  `Impersonate target "chrome" is not available` because the Dockerfile
  installed `yt-dlp[default]`, which does not transitively pull
  `curl_cffi` — `[default]` and `[curl-cffi]` are independent
  optional-dependency groups in yt-dlp's pyproject.toml. Now installs
  `yt-dlp[default,curl-cffi]` so curl_cffi lands in the image with a
  version pinned by yt-dlp itself (single source of truth).

### Changed
- Dockerfile comments rewritten to remove unverifiable claims about
  yt-dlp's internal requirements (`current floor is 2.3` and
  `yt-dlp (2026.06.09+) requires a JavaScript runtime` were either
  load-bearing fabrications or ambiguous historical claims). Now
  documents project decisions and cites the real yt-dlp 2025.11.12
  JS-runtime cutover.
- `requirements.txt` no longer claims `yt-dlp[default]` transitively
  installs curl_cffi. Points at the Dockerfile as the single source of
  truth for yt-dlp + extras versions.

### Build
- CI workflow now builds the image with `load: true`, runs a smoke test
  against the locally-loaded image (verifies `curl_cffi` imports, Chrome
  impersonate target is available, Deno is on PATH), then pushes to
  GHCR. Smoke test failure blocks publication, preventing the class of
  bug where the image builds successfully but fails at runtime from
  reaching production.

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
