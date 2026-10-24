from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from copy_template import tidy_recipe_folder
from config import app_dir


class DownloadError(RuntimeError):
    pass


def _friendly(message: str) -> str:
    text = (message or "").strip() or "Download failed."
    lower = text.lower()
    if any(word in lower for word in ("login", "cookie", "403", "401", "rate-limit", "please wait", "not logged")):
        return (
            text
            + "\nSet Browser cookies to chrome, edge or firefox if Instagram blocks the download."
        )
    return text


def _cookies_opts(cookies_from_browser: str) -> dict:
    if not cookies_from_browser.strip():
        return {}
    return {"cookiesfrombrowser": (cookies_from_browser.strip(),)}


def _ydl_base(cookies_from_browser: str) -> dict:
    opts: dict = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 30,
    }
    opts.update(_cookies_opts(cookies_from_browser))
    return opts


def _hidden_run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("capture_output", True)
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    return subprocess.run(command, **kwargs)


def fetch_info(url: str, cookies_from_browser: str = "") -> dict:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError as YdlError
    except ImportError:
        return _fetch_info_cli(url, cookies_from_browser)
    try:
        with YoutubeDL(_ydl_base(cookies_from_browser)) as ydl:
            info = ydl.extract_info(url, download=False)
    except YdlError as error:
        raise DownloadError(_friendly(str(error))) from error
    except Exception as error:
        raise DownloadError(_friendly(str(error))) from error
    if not info:
        raise DownloadError("Could not read Instagram metadata.")
    return info


def download_media(url: str, folder: Path, cookies_from_browser: str = "") -> None:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError as YdlError
    except ImportError:
        _download_media_cli(url, folder, cookies_from_browser)
        _normalize_files(folder)
        return
    opts = _ydl_base(cookies_from_browser)
    opts["outtmpl"] = str(folder / f"{folder.name}.%(ext)s")
    opts["writethumbnail"] = True
    if shutil.which("ffmpeg"):
        opts["postprocessors"] = [{"key": "FFmpegThumbnailsConvertor", "format": "jpg"}]
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
    except YdlError as error:
        raise DownloadError(_friendly(str(error))) from error
    except Exception as error:
        raise DownloadError(_friendly(str(error))) from error
    _normalize_files(folder)


def _yt_dlp_cmd() -> list[str]:
    for name in ("yt-dlp", "yt-dlp.exe"):
        found = shutil.which(name)
        if found:
            return [found]
    beside = app_dir() / "yt-dlp.exe"
    if beside.is_file():
        return [str(beside)]
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-m", "yt_dlp"]
    raise DownloadError(
        "yt-dlp is missing. Rebuild Reciplate.exe (it bundles yt-dlp), "
        "or put yt-dlp.exe next to the program."
    )


def _fetch_info_cli(url: str, cookies_from_browser: str) -> dict:
    command = [*_yt_dlp_cmd()]
    if cookies_from_browser:
        command += ["--cookies-from-browser", cookies_from_browser]
    command += ["--no-playlist", "-j", "--no-warnings", url]
    try:
        result = _hidden_run(command, text=True, encoding="utf-8", errors="replace", timeout=120)
    except subprocess.TimeoutExpired as error:
        raise DownloadError("Instagram metadata timed out.") from error
    if result.returncode != 0:
        raise DownloadError(_friendly(result.stderr.strip() or "Could not read Instagram metadata."))
    lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
    if not lines:
        raise DownloadError("Could not read Instagram metadata.")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise DownloadError("Instagram metadata was not valid JSON.") from error


def _download_media_cli(url: str, folder: Path, cookies_from_browser: str) -> None:
    command = [*_yt_dlp_cmd()]
    if cookies_from_browser:
        command += ["--cookies-from-browser", cookies_from_browser]
    command += ["--no-playlist", "--write-thumbnail"]
    if shutil.which("ffmpeg"):
        command += ["--convert-thumbnails", "jpg"]
    command += ["-o", str(folder / f"{folder.name}.%(ext)s"), url]
    try:
        result = _hidden_run(command, text=True, encoding="utf-8", errors="replace", timeout=300)
    except subprocess.TimeoutExpired as error:
        raise DownloadError("Instagram download timed out.") from error
    if result.returncode != 0:
        raise DownloadError(_friendly(result.stderr.strip() or "Download failed."))


def _photo_dest(folder: Path) -> Path:
    return folder / f"{folder.name}.jpg"


def _run_ffmpeg(*args: str) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        result = _hidden_run([ffmpeg, "-y", *args], timeout=45)
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def _convert_to_jpg(source: Path, dest: Path) -> bool:
    if source.resolve() == dest.resolve() and source.suffix.lower() in {".jpg", ".jpeg"}:
        return True
    if source.suffix.lower() in {".jpg", ".jpeg"}:
        if dest.exists() and dest.resolve() != source.resolve():
            dest.unlink()
        source.replace(dest)
        return dest.is_file()
    if _run_ffmpeg("-i", str(source), str(dest)) and dest.is_file():
        if source.resolve() != dest.resolve():
            source.unlink(missing_ok=True)
        return True
    try:
        from PIL import Image

        with Image.open(source) as image:
            image.convert("RGB").save(dest, "JPEG", quality=90)
        if source.resolve() != dest.resolve():
            source.unlink(missing_ok=True)
        return dest.is_file()
    except Exception:
        return False


def _extract_frame(folder: Path, dest: Path) -> bool:
    videos = [
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
    ]
    if not videos:
        return False
    return _run_ffmpeg("-ss", "0.8", "-i", str(videos[0]), "-frames:v", "1", str(dest)) and dest.is_file()


def _place_recipe_photo(folder: Path) -> None:
    dest = _photo_dest(folder)
    thumbs = [
        path
        for path in folder.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        and path.name.lower() not in {"sticker-homemade.png"}
    ]
    thumbs.sort(key=lambda path: (path.stem != folder.name, path.suffix.lower() not in {".jpg", ".jpeg"}, path.name))
    if dest.is_file() and dest.stat().st_size > 0:
        for path in thumbs:
            if path.resolve() != dest.resolve():
                path.unlink(missing_ok=True)
        return
    for path in thumbs:
        if _convert_to_jpg(path, dest) and dest.is_file():
            for leftover in thumbs:
                if leftover.exists() and leftover.resolve() != dest.resolve():
                    leftover.unlink(missing_ok=True)
            return
    _extract_frame(folder, dest)


def _normalize_files(folder: Path) -> None:
    for path in list(folder.glob("source.*")):
        if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}:
            target = folder / f"{folder.name}{path.suffix.lower()}"
            if target.exists() and target != path:
                path.unlink(missing_ok=True)
            else:
                path.replace(target)
    _place_recipe_photo(folder)
    tidy_recipe_folder(folder)
