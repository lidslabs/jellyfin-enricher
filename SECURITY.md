# Security Policy

## Reporting a Vulnerability

This is a personal homelab project maintained by one person in spare time.
There is no formal security response team, no embargo process, and no
coordinated disclosure window.

For security-relevant issues, open a public GitHub issue at
https://github.com/lidslabs/jellyfin-enricher/issues.

Public issues are acceptable because the intended deployment is a
self-hosted instance behind a LAN or reverse proxy, not exposed directly
to the public internet. The app validates auth on every request, but
session secret rotation and HTTPS-only cookies are the user's
responsibility to configure (see `.env.example`).

If you believe an issue warrants private disclosure (e.g., a vulnerability
in the auth layer that should not be publicized until a fix ships),
contact via the email on [my GitHub profile](https://github.com/lidslabs).

## Supported Versions

Only the most recent tagged release receives fixes. Older tags remain
pullable from ghcr.io for rollback purposes but are not patched.

## Dependency Security

`yt-dlp` is the largest moving target. Bumps to yt-dlp ship as patch
releases (e.g., v0.1.0 → v0.1.1). If you operate a public-facing
instance, follow yt-dlp releases for security advisories.
