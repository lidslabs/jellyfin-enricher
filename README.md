# jellyfin-enricher

Web UI for backfilling missing **theme songs** (TV shows) and **trailers** (movies)
in a Jellyfin library by pasting YouTube video IDs. Source of truth for "is this
missing?" is the filesystem — not Jellyfin's metadata cache.

Second image in the `lidslabs/` family, after
[`lidslabs/jellyfin-hdr`](https://github.com/lidslabs/jellyfin-hdr).

## What it does

1. Hits Jellyfin's `/Items` endpoint for all Movies (trailers) or Series (themes).
2. Walks the filesystem for each item, checking for the expected extras file.
3. Renders the missing items as a list with poster, title, and a YouTube ID input.
4. On submit, runs `yt-dlp` in a background task and streams progress into the row.
5. **Skip** removes the item for this session only. **Skip Permanently** stores it
   in SQLite; manage the permanent list from the Permanent Skips tab.

## File conventions

| Type    | Path                                                |
|---------|-----------------------------------------------------|
| Theme   | `<show_root>/theme.mp3` (or `.flac`, `.m4a`, etc.)  |
| Trailer | `<movie_folder>/<MovieName> (Year)-trailer.mp4`     |

Trailer subfolder form (`trailers/*.mp4`) is also detected when scanning.

## Quick start

```sh
docker pull ghcr.io/lidslabs/jellyfin-enricher:latest
```

Or pin a specific version (recommended for production):

```sh
docker pull ghcr.io/lidslabs/jellyfin-enricher:v0.1.0
```

Setup:

1. Create a Jellyfin API key (Dashboard → API Keys → +).
2. Copy `.env.example` to `.env` and fill in:
   - `JELLYFIN_API_KEY`
   - `ENRICHER_USER` and `ENRICHER_PASSWORD` (your login credentials)
   - `SESSION_SECRET` — generate with:
```sh
     python -c "import secrets; print(secrets.token_urlsafe(64))"
```
     Rotating this value invalidates all existing sessions; keep it stable.

**Note on `.env` syntax:** Do not put inline comments after a value
   (e.g. `SPLASH_OVERLAY_OPACITY=0.5  # 0-1`). The parser takes the rest
   of the line as the value, which will fail validation at startup. Put
   descriptive comments on the line above the variable instead.

3. Adjust `docker-compose.yml` media volumes to match your Jellyfin mounts.
   The enricher resolves file existence against in-container paths, so mounting
   media at the same paths Jellyfin sees avoids needing `PATH_MAPPINGS`.
4. Pre-create the data directory with the right ownership. **This step is required**
   because bind mounts override the image's baked ownership — without it, the
   container starts as uid 1000 and can't write the SQLite file:
```sh
   mkdir -p data && sudo chown 1000:1000 data
```
   (Use whatever `PUID:PGID` you set if you build locally.)
5. *(Optional)* Drop a splash image at `./data/splash.jpg` (or `.png`/`.webp`)
   for the login page background. Tune via `SPLASH_OVERLAY_OPACITY` (0.0 = no
   dark overlay, 1.0 = fully dark) and `SPLASH_BLUR` (`"4px"`, `"8px"`, or empty
   for no blur).
6. *(Optional)* Drop your own icon at `./data/jellyfin-icon.svg` to override
   the bundled fallback. Useful for using the exact official Jellyfin icon —
   download it from the
   [jellyfin-ux repo](https://github.com/jellyfin/jellyfin-ux/blob/master/branding/SVG/icon-transparent.svg)
   or [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Jellyfin_-_icon-transparent.svg)
   and place it in your `./data/` directory. Takes effect within ~5 minutes
   (cache TTL) without a restart.
7. `docker compose up -d`
8. Browse to `http://127.0.0.1:8765/`. You'll be redirected to a login page;
   sign in with the credentials from `.env`.

## How it behaves

- **Filesystem is the source of truth.** The scanner re-runs each time you load
  a tab. Jellyfin's metadata cache is consulted only for item titles, posters,
  TMDB IDs, and the canonical media file path — the *presence* of `theme.mp3`
  or a `-trailer.mp4` is verified by reading the filesystem directly. This
  means deleting a theme file from disk makes the show reappear in the missing
  list on the next scan, with no Jellyfin library refresh needed.

- **Scans are idempotent.** Re-scanning never double-downloads. A successful
  download writes the extras file in place; the next scan sees it and the item
  drops off the missing list.

- **Failed downloads leave nothing behind.** yt-dlp's `--no-part` is not used;
  yt-dlp itself handles cleanup of partial files on failure. The row shows the
  error message inline so you can adjust the YouTube ID and retry without
  reloading.

- **Session vs. permanent skips.** A session skip is in-memory only and resets
  when you reload the page or restart the container. A permanent skip is
  persisted in SQLite at `/var/lib/enricher/enricher.db` and survives container
  rebuilds. Manage the permanent list from the **Permanent Skips** tab.

- **Skip-by-TMDB-ID, not by file path.** Permanent skips key on the Jellyfin
  item ID, so moving or renaming files doesn't lose the skip state — but
  re-importing the library item under a different Jellyfin ID will (since
  Jellyfin reassigns IDs on re-add).

- **Duplicate submissions are queued, not blocked.** Submitting two YouTube
  IDs for the same item in rapid succession will run both yt-dlp invocations
  serially. The second one wins (overwrites the first's output). This is by
  design — sometimes the first ID turns out to be wrong and you want to fix
  it without waiting for the bad one to finish.

- **Settings overrides take effect on the next request.** Editing Jellyfin URL
  or API key on the `/settings` page writes to the DB, no restart needed. The
  Source indicator (`DB`, `env`, or `unset`) shows where the active value came
  from at any moment.

## Auth model

Session-based login via Starlette's `SessionMiddleware` (signed cookies):

- Two auth backends, both producing the same session:
  - **Local** — username/password validated against `ENRICHER_USER` /
    `ENRICHER_PASSWORD` with constant-time comparison.
  - **Jellyfin** — credentials validated against your Jellyfin server via
    `/Users/AuthenticateByName`. Only users with the `IsAdministrator` policy
    flag are accepted, since this tool writes to the shared media library.
- The login screen defaults to local; click "Sign in with Jellyfin" to switch.
  The Jellyfin option is disabled until Jellyfin is configured in Settings.
- Successful login sets a signed cookie carrying the session; no server-side
  session table.
- Session lifetime defaults to 7 days; configurable via `SESSION_MAX_AGE`.
- `SameSite=Lax` cookies; `HttpOnly`; set `SESSION_HTTPS_ONLY=true` when
  serving behind TLS.
- HTMX 401 responses include `HX-Redirect: /login` so the browser navigates
  cleanly instead of swapping a login page into a partial.
- Sign out via the link in the top-right of the topbar.

## Settings page

`/settings` (accessible from the topbar) lets you edit Jellyfin connection
details at runtime:

- **Jellyfin URL** and **API Key** — DB values override env values. Saving
  stores in the SQLite `settings` table; new values take effect on the next
  request, no restart needed.
- The Source indicator (`DB`, `env`, or `unset`) shows where the active value
  came from.
- **Test Connection** hits `/System/Info` against the effective URL+key to
  verify both before relying on them.
- **Drop DB override** removes a DB row so the env value (if set) becomes the
  active value again.

Bootstrap settings (login credentials, session secret, splash) remain env-only
and require a container restart to change.

## YouTube ID input

The input accepts any of:

- Bare 11-char ID: `dQw4w9WgXcQ`
- Full URL pasted as-is: `https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=...`
- Short URL: `https://youtu.be/dQw4w9WgXcQ`

Whatever you paste, only the 11-character ID is extracted and passed to yt-dlp.

## When YouTube starts asking for sign-in

Export browser cookies into `data/cookies.txt` (Netscape format), then set
`YTDLP_COOKIES_FILE=/var/lib/enricher/cookies.txt` in the env. The
[get-cookies.txt LOCALLY](https://github.com/kairi003/Get-cookies.txt-LOCALLY)
extension is one option. Use a throwaway YouTube account.

## Upgrading yt-dlp

yt-dlp moves fast — YouTube changes break extraction roughly weekly, and yt-dlp
ships fixes shortly after. This image pins a specific yt-dlp version at build
time so deployments are reproducible. To pick up a new version:

- Watch the [yt-dlp releases page](https://github.com/yt-dlp/yt-dlp/releases) for
  the current stable release.
- Pull a newer enricher tag once one is published:
```sh
  docker pull ghcr.io/lidslabs/jellyfin-enricher:latest
  docker compose up -d
```
- yt-dlp bumps ship as patch-level enricher releases (e.g., v0.1.0 → v0.1.1).
- If you build locally, edit the `YTDLP_VERSION` ARG in `Dockerfile` and
  `docker compose build --no-cache`.

## Path translation

If your enricher container mounts media at different paths than Jellyfin does,
set `PATH_MAPPINGS` in the env:
PATH_MAPPINGS=/mnt/jellyfin/movies:/data/media1/movies,/mnt/jellyfin/tv:/data/media1/tv

Items whose paths can't be resolved inside the container are shown with a
warning and have their download button disabled.

## Threat model

- **Auth**: signed-cookie sessions via Starlette's `SessionMiddleware` over
  HTTP. Fine for `127.0.0.1` bind and LAN access behind a TLS-terminating
  reverse proxy (set `SESSION_HTTPS_ONLY=true` in that case). Do **not** expose
  this to the internet without layered auth — anyone with credentials can
  trigger arbitrary YouTube downloads and write files anywhere the container
  has write access.
- **Open-redirect prevention**: the `?next=` parameter on `/login` is
  validated to only allow relative same-origin paths starting with `/`.
- **Splash route**: the `/splash` endpoint is unauthenticated by design
  (the login page references it before any session exists). Only files
  named `splash.{jpg,jpeg,png,webp}` in the data directory are served.
- **Mount surface**: write access to every directory under your media mounts.
  yt-dlp invocations are constructed with `subprocess_exec` (no shell), the
  YouTube ID is regex-validated to the 11-char alphabet before reaching the
  command line, and output paths come from Jellyfin metadata only.
- **API key**: the Jellyfin API key has admin scope. It lives in the env only;
  poster fetches are proxied so the key never reaches the browser.
- **Storage**: SQLite at `/var/lib/enricher/enricher.db`. No secrets in it.

## Extending: adding new extras types

The four-step recipe (see `app/extras.py` for the registry):

1. Add an `ExtrasType` enum member.
2. Add an `ExtrasDefinition` entry; leave `ui_exposed=False` until ready.
3. Add a `*_exists()` check in `app/scanner.py` for the file convention.
4. Add a branch in `app/downloader.py` `_build_command()` for yt-dlp invocation.

The registry is intentionally minimal in v0.1.0 — only themes and trailers
ship. The architecture supports any extras type Jellyfin recognizes
(behindthescenes, interview, featurette, deletedscene, etc.); they're absent
from the registry rather than scaffolded-but-hidden because every new type
also needs scanner and downloader work to be useful.

## Roadmap

Not committed work — these are candidates likely to land in future minor releases:

- **Additional extras types** — behind-the-scenes, interviews, featurettes,
  deleted scenes. Architecture supports it; needs scanner + downloader work
  per type.
- **Bulk queue** — paste many IDs at once before submitting, batch confirm.
- **Retry/resume of partial downloads** — currently a failed download requires
  re-pasting the ID.
- **Audit log view** — a `download_history` table exists in SQLite but is
  not surfaced in the UI.
- **WebSocket-based job updates** — HTMX polling is fine for the scale of
  this tool today; WebSocket would lower latency on long downloads.

Open an issue if you want to nudge any of these forward, or have a use case
not on the list.

## License

MIT. See [`LICENSE`](./LICENSE).

The bundled Jellyfin icon is CC-BY-SA 4.0 and is used to indicate
interoperability with Jellyfin. See [`NOTICE`](./NOTICE) for attribution.
This tool is not affiliated with the Jellyfin project.

## Reporting issues

Bugs, regressions, questions: open a GitHub issue. See [`SECURITY.md`](./SECURITY.md)
for security-specific reports.
