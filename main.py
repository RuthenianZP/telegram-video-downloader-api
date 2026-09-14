import os
import shutil
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel


app = FastAPI(title="Telegram Video Downloader API")


class DownloadRequest(BaseModel):
    url: str
    format: str = "mp4"
    quality: str | None = None


def get_short_filename(info: dict, ext: str = "mp4") -> str:
    """
    Creates a short filename using the media ID instead of the title.
    This prevents 'Filename too long' errors caused by long Facebook titles.
    """
    media_id = info.get("id") or uuid.uuid4().hex[:12]

    # Keep only safe filename characters.
    safe_id = "".join(
        char for char in str(media_id)
        if char.isalnum() or char in ("-", "_")
    )

    if not safe_id:
        safe_id = uuid.uuid4().hex[:12]

    return f"{safe_id}.{ext}"


def download_video(url: str, quality: str | None = None):
    temp_dir = tempfile.mkdtemp(prefix="video_")

    try:
        # First get metadata without downloading.
        info_options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }

        with yt_dlp.YoutubeDL(info_options) as ydl:
            info = ydl.extract_info(url, download=False)

        # MP4-friendly format selection.
        if quality:
            format_selector = (
                f"bestvideo[height<={quality}][ext=mp4]+"
                f"bestaudio[ext=m4a]/"
                f"best[height<={quality}][ext=mp4]/"
                f"best[height<={quality}]"
            )
        else:
            format_selector = (
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                "best[ext=mp4]/best"
            )

        # IMPORTANT:
        # Use ID instead of %(title)s.
        output_template = str(
            Path(temp_dir) / "%(id)s.%(ext)s"
        )

        download_options = {
            "format": format_selector,
            "outtmpl": output_template,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
        }

        with yt_dlp.YoutubeDL(download_options) as ydl:
            ydl.download([url])

        # Find the resulting video file.
        video_files = list(Path(temp_dir).glob("*.mp4"))

        if not video_files:
            # Sometimes yt-dlp leaves another extension before merging.
            all_files = [
                p for p in Path(temp_dir).iterdir()
                if p.is_file() and not p.name.endswith(".part")
            ]

            if not all_files:
                raise RuntimeError("Downloaded file was not found.")

            video_file = all_files[0]
        else:
            video_file = video_files[0]

        # Rename to a guaranteed short filename.
        final_name = get_short_filename(info, "mp4")
        final_path = Path(temp_dir) / final_name

        if video_file != final_path:
            shutil.move(str(video_file), str(final_path))

        return str(final_path), temp_dir

    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


@app.get("/")
def root():
    return {"status": "ok", "service": "telegram-video-downloader"}


@app.get("/download")
def download_get(
    url: str = Query(...),
    format: str = Query("mp4"),
    quality: str | None = Query(None),
):
    if format != "mp4":
        raise HTTPException(
            status_code=400,
            detail="Only mp4 format is supported."
        )

    try:
        file_path, temp_dir = download_video(url, quality)

        return FileResponse(
            file_path,
            media_type="video/mp4",
            filename=Path(file_path).name,
            background=None,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Download error: {exc}"
        )


@app.post("/download")
def download_post(request: DownloadRequest):
    if request.format != "mp4":
        raise HTTPException(
            status_code=400,
            detail="Only mp4 format is supported."
        )

    try:
        file_path, temp_dir = download_video(
            request.url,
            request.quality,
        )

        return FileResponse(
            file_path,
            media_type="video/mp4",
            filename=Path(file_path).name,
            background=None,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Download error: {exc}"
        )


@app.get("/info")
def info(url: str = Query(...)):
    try:
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info(url, download=False)

        return {
            "id": data.get("id"),
            "title": data.get("title"),
            "duration": data.get("duration"),
            "webpage_url": data.get("webpage_url"),
            "ext": data.get("ext"),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Info error: {exc}"
        )


@app.get("/formats")
def formats(url: str = Query(...)):
    try:
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info(url, download=False)

        result = []

        for fmt in data.get("formats", []):
            result.append({
                "format_id": fmt.get("format_id"),
                "ext": fmt.get("ext"),
                "height": fmt.get("height"),
                "width": fmt.get("width"),
                "fps": fmt.get("fps"),
                "vcodec": fmt.get("vcodec"),
                "acodec": fmt.get("acodec"),
                "filesize": fmt.get("filesize"),
            })

        return {"formats": result}

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Formats error: {exc}"
        )
