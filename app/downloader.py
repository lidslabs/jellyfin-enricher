"""yt-dlp wrapper with background job execution and live log streaming.

Jobs are tracked in process memory; this is appropriate for a single-user
homelab tool. On container restart, in-flight jobs are lost — the
permanent record lives in download_history.
"""

import asyncio
import logging
import re
import shlex
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .config import settings
from .db import record_download
from .extras import ExtrasType
from .scanner import MediaItem

log = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "success", "error"]

# 11-character YouTube video ID alphabet
_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_URL_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


@dataclass
class Job:
    id: str
    jellyfin_id: str
    extras_type: ExtrasType
    title: str
    youtube_id: str
    status: JobStatus = "queued"
    log_lines: list[str] = field(default_factory=list)
    error: str | None = None
    output_path: str | None = None


_jobs: dict[str, Job] = {}


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def normalize_youtube_id(raw: str) -> str:
    """Accept a bare 11-char ID or a pasted URL; return the canonical ID.

    Raises ValueError if no valid ID can be extracted.
    """
    raw = raw.strip()
    if _YOUTUBE_ID_RE.match(raw):
        return raw
    m = _YOUTUBE_URL_RE.search(raw)
    if m:
        return m.group(1)
    raise ValueError(f"Could not extract a valid YouTube ID from: {raw!r}")


# --- command construction ---

def _theme_output_template(show_path: Path) -> str:
    # yt-dlp will substitute %(ext)s with the final container extension.
    return str(show_path / "theme.%(ext)s")


def _trailer_output_template(item: MediaItem) -> str:
    # Convention: '<MovieName> (Year)-trailer.<ext>' alongside the movie file.
    # Jellyfin reports the movie file path for Movie items.
    parent = item.container_path.parent
    base = (
        f"{item.title} ({item.year})-trailer"
        if item.year
        else f"{item.title}-trailer"
    )
    # We do not sanitize file-illegal characters here; if Jellyfin accepts the
    # movie name on disk, the trailer name with the same prefix is fine too.
    return str(parent / f"{base}.%(ext)s")


def _build_command(
    item: MediaItem, extras_type: ExtrasType, youtube_id: str
) -> tuple[list[str], str]:
    url = f"https://www.youtube.com/watch?v={youtube_id}"

    if extras_type == ExtrasType.THEME:
        output_template = _theme_output_template(item.container_path)
        cmd = [
            "yt-dlp",
            "--no-progress",
            "--newline",
            "-x",
            "--audio-format", settings.theme_audio_format,
            "--audio-quality", settings.theme_audio_quality,
            "-o", output_template,
        ]
    elif extras_type == ExtrasType.TRAILER:
        output_template = _trailer_output_template(item)
        cmd = [
            "yt-dlp",
            "--no-progress",
            "--newline",
            "-f",
            f"bestvideo[height<={settings.trailer_max_height}]+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", output_template,
        ]
    else:
        raise ValueError(f"Unsupported extras type: {extras_type}")

    if settings.ytdlp_cookies_file:
        cmd.extend(["--cookies", settings.ytdlp_cookies_file])

    if settings.ytdlp_impersonate:
        cmd.extend(["--impersonate", settings.ytdlp_impersonate])

    if settings.ytdlp_extra_args:
        # shlex preserves quoted args correctly
        cmd.extend(shlex.split(settings.ytdlp_extra_args))

    cmd.append(url)
    return cmd, output_template


# --- job execution ---

async def run_download(
    item: MediaItem, extras_type: ExtrasType, youtube_id: str
) -> Job:
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        jellyfin_id=item.jellyfin_id,
        extras_type=extras_type,
        title=item.display_title,
        youtube_id=youtube_id,
    )
    _jobs[job_id] = job
    asyncio.create_task(_execute(job, item, extras_type))
    return job


async def _execute(job: Job, item: MediaItem, extras_type: ExtrasType) -> None:
    job.status = "running"
    output_template = ""
    try:
        if not item.path_accessible:
            raise RuntimeError(
                f"Refusing to download — container cannot see {item.container_path}"
            )

        cmd, output_template = _build_command(item, extras_type, job.youtube_id)
        job.log_lines.append("$ " + " ".join(shlex.quote(c) for c in cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None

        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            job.log_lines.append(line)
            # Cap log buffer so a misbehaving download can't OOM the process.
            if len(job.log_lines) > 500:
                job.log_lines = job.log_lines[-500:]

        rc = await proc.wait()
        if rc != 0:
            job.status = "error"
            job.error = f"yt-dlp exited with code {rc}"
        else:
            job.status = "success"
            job.output_path = output_template

        record_download(
            jellyfin_id=item.jellyfin_id,
            extras_type=extras_type.value,
            title=item.display_title,
            youtube_id=job.youtube_id,
            target_path=output_template,
            success=(job.status == "success"),
            error=job.error,
        )
    except Exception as e:
        log.exception("Download failed for %s", item.display_title)
        job.status = "error"
        job.error = str(e)
        try:
            record_download(
                jellyfin_id=item.jellyfin_id,
                extras_type=extras_type.value,
                title=item.display_title,
                youtube_id=job.youtube_id,
                target_path=output_template,
                success=False,
                error=str(e),
            )
        except Exception:
            log.exception("Failed to record download history")
