"""FastAPI routes and app lifespan."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .auth import NotAuthenticatedError, require_session, verify_login_credentials
from .config import (
    settings,
    effective_jellyfin_url,
    effective_jellyfin_api_key,
    jellyfin_configured,
)
from .db import (
    add_permanent_skip,
    delete_setting,
    get_setting,
    init_db,
    list_permanent_skips,
    remove_permanent_skip,
    set_setting,
)
from .downloader import get_job, normalize_youtube_id, run_download
from .extras import EXTRAS, ExtrasType, ui_exposed_extras
from .jellyfin import (
    JellyfinClient,
    JellyfinNotConfiguredError,
    authenticate_user as jellyfin_authenticate_user,
    test_connection as jellyfin_test_connection,
)
from .scanner import scan_missing

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("Jellyfin Enricher started. Data dir: %s", settings.data_dir)
    yield


app = FastAPI(title="Jellyfin Enricher", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=settings.session_https_only,
)

app_dir = Path(__file__).parent
templates = Jinja2Templates(directory=str(app_dir / "templates"))
app.mount("/static", StaticFiles(directory=str(app_dir / "static")), name="static")


_session_skips: set[tuple[str, str]] = set()


# --- splash ---

_SPLASH_CANDIDATES = ("splash.jpg", "splash.jpeg", "splash.png", "splash.webp")
_SPLASH_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

_ICON_CANDIDATES = ("jellyfin-icon.svg", "icon.svg")
_BUNDLED_ICON = app_dir / "static" / "jellyfin-icon.svg"


def _find_splash_file() -> Path | None:
    for name in _SPLASH_CANDIDATES:
        candidate = settings.data_dir / name
        if candidate.is_file():
            return candidate
    return None


def _find_icon_file() -> Path:
    """User override in data dir wins; bundled SVG is the fallback."""
    for name in _ICON_CANDIDATES:
        candidate = settings.data_dir / name
        if candidate.is_file():
            return candidate
    return _BUNDLED_ICON


# --- redirect-on-no-session handling ---

def _is_safe_next(path: str) -> bool:
    return bool(path) and path.startswith("/") and not path.startswith("//")


@app.exception_handler(NotAuthenticatedError)
async def _not_authenticated_handler(request: Request, _exc: NotAuthenticatedError):
    if request.headers.get("HX-Request"):
        return Response(status_code=401, headers={"HX-Redirect": "/login"})
    next_path = request.url.path
    if request.url.query:
        next_path += f"?{request.url.query}"
    location = f"/login?next={quote(next_path, safe='/?=&')}"
    return RedirectResponse(url=location, status_code=303)


# --- public routes ---

@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/splash")
def splash():
    path = _find_splash_file()
    if not path:
        raise HTTPException(404, "No splash image configured")
    mime = _SPLASH_MIME.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "public, max-age=300"})


@app.get("/icon")
def icon():
    """Serve the Jellyfin icon. User-provided file in data dir wins over bundled.

    Place jellyfin-icon.svg (or icon.svg) in the enricher data directory to
    override the fallback. Cache time is short so swaps take effect quickly.
    """
    path = _find_icon_file()
    return FileResponse(
        path,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


def _render_login(
    request: Request,
    auth_mode: str = "local",
    error: str | None = None,
    next_path: str = "/",
    status_code: int = 200,
):
    """Single entry point for rendering the login template in either mode."""
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "auth_mode": auth_mode,
            "next": next_path if _is_safe_next(next_path) else "/",
            "error": error,
            "splash_available": _find_splash_file() is not None,
            "splash_overlay_opacity": settings.splash_overlay_opacity,
            "splash_blur": settings.splash_blur,
            "jellyfin_configured": jellyfin_configured(),
        },
        status_code=status_code,
    )


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/"):
    if request.session.get("user"):
        return RedirectResponse(
            url=next if _is_safe_next(next) else "/",
            status_code=303,
        )
    return _render_login(request, auth_mode="local", next_path=next)


@app.get("/login/jellyfin", response_class=HTMLResponse)
def login_form_jellyfin(request: Request, next: str = "/"):
    if request.session.get("user"):
        return RedirectResponse(
            url=next if _is_safe_next(next) else "/",
            status_code=303,
        )
    return _render_login(request, auth_mode="jellyfin", next_path=next)


@app.post("/login", response_class=HTMLResponse)
def login_submit_local(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = "/",
):
    if not verify_login_credentials(username, password):
        return _render_login(
            request, auth_mode="local",
            error="Invalid username or password.",
            next_path=next, status_code=401,
        )
    request.session.clear()
    request.session["user"] = username
    request.session["auth_method"] = "local"
    target = next if _is_safe_next(next) else "/"
    return RedirectResponse(url=target, status_code=303)


@app.post("/login/jellyfin", response_class=HTMLResponse)
def login_submit_jellyfin(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = "/",
):
    if not jellyfin_configured():
        return _render_login(
            request, auth_mode="jellyfin",
            error="Jellyfin is not configured yet. Sign in locally and add it on the Settings page.",
            next_path=next, status_code=400,
        )

    user = jellyfin_authenticate_user(username, password)
    if user is None:
        return _render_login(
            request, auth_mode="jellyfin",
            error="Invalid Jellyfin credentials.",
            next_path=next, status_code=401,
        )

    is_admin = user.get("Policy", {}).get("IsAdministrator", False)
    if not is_admin:
        return _render_login(
            request, auth_mode="jellyfin",
            error="Only Jellyfin administrators can use this tool.",
            next_path=next, status_code=403,
        )

    request.session.clear()
    request.session["user"] = user.get("Name", username)
    request.session["auth_method"] = "jellyfin"
    request.session["jellyfin_user_id"] = user.get("Id", "")
    target = next if _is_safe_next(next) else "/"
    return RedirectResponse(url=target, status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# --- authenticated app routes ---

@app.get("/", response_class=HTMLResponse)
def index(request: Request, user: str = Depends(require_session)):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "extras_types": ui_exposed_extras(),
            "user": user,
            "auth_method": request.session.get("auth_method", "local"),
        },
    )


@app.get("/api/scan", response_class=HTMLResponse)
def scan(
    request: Request,
    extras_type: str,
    refresh: int = 0,
    _user: str = Depends(require_session),
):
    try:
        ext_enum = ExtrasType(extras_type)
    except ValueError:
        raise HTTPException(400, "Invalid extras_type")

    if refresh:
        global _session_skips
        _session_skips = {s for s in _session_skips if s[1] != extras_type}

    all_items = scan_missing(ext_enum)
    visible = [
        i for i in all_items
        if (i.jellyfin_id, extras_type) not in _session_skips
        and not i.permanently_skipped
    ]

    return templates.TemplateResponse(
        request,
        "_item_list.html",
        {
            "items": visible,
            "extras_type": ext_enum,
            "extras_def": EXTRAS[ext_enum],
            "total_missing": len(all_items),
            "shown": len(visible),
        },
    )


@app.post("/api/download", response_class=HTMLResponse)
async def download(
    request: Request,
    jellyfin_id: str = Form(...),
    extras_type: str = Form(...),
    youtube_input: str = Form(...),
    _user: str = Depends(require_session),
):
    try:
        ext_enum = ExtrasType(extras_type)
    except ValueError:
        raise HTTPException(400, "Invalid extras_type")

    try:
        yt_id = normalize_youtube_id(youtube_input)
    except ValueError as e:
        resp = templates.TemplateResponse(
            request, "_toast.html",
            {"message": str(e), "level": "error"},
        )
        resp.headers["HX-Retarget"] = "#toast-area"
        resp.headers["HX-Reswap"] = "afterbegin"
        return resp

    items = scan_missing(ext_enum)
    matching = next((i for i in items if i.jellyfin_id == jellyfin_id), None)
    if not matching:
        resp = templates.TemplateResponse(
            request, "_toast.html",
            {"message": "Item not found in current scan (already resolved?)", "level": "error"},
        )
        resp.headers["HX-Retarget"] = "#toast-area"
        resp.headers["HX-Reswap"] = "afterbegin"
        return resp

    job = await run_download(matching, ext_enum, yt_id)
    return templates.TemplateResponse(request, "_job_status.html", {"job": job})


@app.get("/api/job/{job_id}", response_class=HTMLResponse)
def job_status(request: Request, job_id: str, _user: str = Depends(require_session)):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return templates.TemplateResponse(request, "_job_status.html", {"job": job})


@app.post("/api/job/{job_id}/dismiss", response_class=HTMLResponse)
def dismiss_job(job_id: str, _user: str = Depends(require_session)):
    return HTMLResponse("")


@app.post("/api/skip", response_class=HTMLResponse)
def skip(
    jellyfin_id: str = Form(...),
    extras_type: str = Form(...),
    permanent: int = Form(0),
    title: str = Form(""),
    year: int | None = Form(None),
    _user: str = Depends(require_session),
):
    if permanent:
        add_permanent_skip(jellyfin_id, extras_type, title, year, reason="user")
    else:
        _session_skips.add((jellyfin_id, extras_type))
    return HTMLResponse("")


@app.get("/api/image/{item_id}")
def proxy_image(item_id: str, _user: str = Depends(require_session)):
    try:
        with JellyfinClient() as jf:
            data, content_type = jf.fetch_primary_image(item_id)
    except JellyfinNotConfiguredError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(404, str(e))
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "max-age=3600"})


@app.get("/api/permanent-skips", response_class=HTMLResponse)
def permanent_skips_view(request: Request, _user: str = Depends(require_session)):
    skips = list_permanent_skips()
    return templates.TemplateResponse(request, "_skip_list.html", {"skips": skips})


@app.post("/api/permanent-skips/remove", response_class=HTMLResponse)
def remove_skip(
    jellyfin_id: str = Form(...),
    extras_type: str = Form(...),
    _user: str = Depends(require_session),
):
    remove_permanent_skip(jellyfin_id, extras_type)
    return HTMLResponse("")


# --- settings ---

def _settings_context(saved: bool = False, test_result: tuple[bool, str] | None = None) -> dict:
    """Snapshot of effective values for the settings template."""
    return {
        "jellyfin_url": effective_jellyfin_url(),
        "jellyfin_api_key_set": bool(effective_jellyfin_api_key()),
        "jellyfin_url_source": "DB" if get_setting("jellyfin_url") else ("env" if settings.jellyfin_url else "unset"),
        "jellyfin_api_key_source": "DB" if get_setting("jellyfin_api_key") else ("env" if settings.jellyfin_api_key else "unset"),
        "extras_types": ui_exposed_extras(),
        "saved": saved,
        "test_result": test_result,
    }


@app.get("/settings", response_class=HTMLResponse)
def settings_view(
    request: Request,
    user: str = Depends(require_session),
    saved: int = 0,
):
    ctx = _settings_context(saved=bool(saved))
    ctx.update({
        "user": user,
        "auth_method": request.session.get("auth_method", "local"),
    })
    return templates.TemplateResponse(request, "settings.html", ctx)


@app.post("/settings", response_class=HTMLResponse)
def settings_save(
    request: Request,
    jellyfin_url: str = Form(""),
    jellyfin_api_key: str = Form(""),
    user: str = Depends(require_session),
):
    url = jellyfin_url.strip()
    key = jellyfin_api_key.strip()

    if url:
        set_setting("jellyfin_url", url)
    elif get_setting("jellyfin_url") is not None:
        # explicit empty -> remove DB override, fall back to env
        delete_setting("jellyfin_url")

    if key:
        # only set if a new key was actually provided; empty means "keep current"
        set_setting("jellyfin_api_key", key)

    return RedirectResponse(url="/settings?saved=1", status_code=303)


@app.post("/settings/test", response_class=HTMLResponse)
def settings_test(request: Request, user: str = Depends(require_session)):
    result = jellyfin_test_connection()
    ctx = _settings_context(test_result=result)
    ctx.update({
        "user": user,
        "auth_method": request.session.get("auth_method", "local"),
    })
    return templates.TemplateResponse(request, "settings.html", ctx)


@app.post("/settings/reset/jellyfin_api_key", response_class=HTMLResponse)
def settings_reset_api_key(_user: str = Depends(require_session)):
    """Drop the DB override for the API key so the env value (if any) is used."""
    delete_setting("jellyfin_api_key")
    return RedirectResponse(url="/settings?saved=1", status_code=303)
