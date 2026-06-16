#!/usr/bin/env bash
# Cut a release: tag and push.
# Bump VERSION (and any Dockerfile ARG version pins) BEFORE running.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
    echo "ERROR: working tree dirty. Commit version bump first." >&2
    git status --short >&2
    exit 1
fi

VERSION="$(cat VERSION)"
TAG="v${VERSION}"

if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "ERROR: tag $TAG already exists. Bump VERSION." >&2
    exit 1
fi

if [[ ! "$TAG" =~ -(rc|alpha|beta|dev)\. ]]; then
    echo "==> $TAG is a NORMAL release (will appear as 'Latest' on GitHub)."
    read -r -p "==> Continue? [y/N] " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "Aborted. Bump VERSION to e.g. ${VERSION%-*}-rc.1 for a pre-release." >&2
        exit 0
    fi
fi

echo "==> Tagging $TAG"
git tag -a "$TAG" -m "Release $TAG"

echo "==> Pushing main + tag"
git push origin main
git push origin "$TAG"

echo
echo "Done. GHA will build and publish:"
echo "  ghcr.io/lidslabs/jellyfin-enricher:${TAG}"
echo "  ghcr.io/lidslabs/jellyfin-enricher:latest"
echo
echo "Watch:  https://github.com/lidslabs/jellyfin-enricher/actions"
