#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reciplate companion: searchable HTML gallery per recipe section (PDF, DOCX, video, images).

Point it at the Reciplate library root (Kochen / Backen) or at one section.
Each gallery has search, type filters, inline video, and the full recipe on click.

If a folder only has a DOCX, Word or LibreOffice prints a PDF beside it (the DOCX stays).
Optional: Pillow, PyMuPDF, OpenCV. Folders named `ignore` are skipped; thumbs go in images/.

  python media_overview.py
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import html
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent
for _p in (_ROOT, _ROOT / "lib", _ROOT.parent):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception:
    tk = None  # type: ignore
    filedialog = None  # type: ignore
    messagebox = None  # type: ignore
    ttk = None  # type: ignore

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None  # type: ignore

try:
    import cv2  # type: ignore
except Exception:
    cv2 = None  # type: ignore

try:
    from PIL import Image
except Exception:
    Image = None  # type: ignore

THUMB_MAX_WIDTH = 1200
PAGE_MAX_WIDTH = 1800
IGNORE_DIR_NAMES = {"ignore"}
_FONT = "Segoe UI"
_FALLBACK_HTML_FONT_CSS = """
@font-face {
  font-family: "Toolbox Sans";
  src: local("Segoe UI Variable Text"), local("Segoe UI");
  unicode-range: U+0000-00FF, U+0100-024F, U+1E00-1EFF, U+2000-206F, U+2070-209F, U+20A0-20CF;
}
@font-face {
  font-family: "Toolbox Sans";
  src: local("Meiryo UI"), local("Meiryo"), local("Yu Gothic UI"), local("BIZ UDPGothic");
  unicode-range: U+3000-303F, U+3040-309F, U+30A0-30FF, U+31F0-31FF, U+3200-32FF, U+3400-4DBF, U+4E00-9FFF, U+F900-FAFF, U+FF00-FFEF;
}
html, body, button, input, textarea, select {
  font-family: "Toolbox Sans", "Meiryo UI", "Yu Gothic UI", "Segoe UI", sans-serif;
  line-height: 1.55;
}
"""


def _add_common() -> None:
    for candidate in (_ROOT.parent, _ROOT):
        if (candidate / "common" / "ui.py").is_file():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)
            return


def html_font_css() -> str:
    _add_common()
    try:
        from common.ui import HTML_FONT_CSS

        return HTML_FONT_CSS
    except ImportError:
        return _FALLBACK_HTML_FONT_CSS


def explain(de: str, ja: str, en: str = "") -> str:
    _add_common()
    try:
        from common.ui import explain as shared

        return shared(de, ja, en)
    except ImportError:
        parts = [part.rstrip() for part in (en, de, ja) if part and part.strip()]
        return "\n".join(parts)


def ui_font(size: int | None = None, *styles: str) -> tuple:
    _add_common()
    try:
        from common.ui import ui_font as shared

        return shared(size, *styles)
    except ImportError:
        used = 12 if size is None else size
        return (_FONT, used, *styles) if styles else (_FONT, used)


def ui_small_font(*styles: str) -> tuple:
    _add_common()
    try:
        from common.ui import ui_small_font as shared

        return shared(*styles)
    except ImportError:
        return ui_font(10, *styles)


def ui_title_font() -> tuple:
    _add_common()
    try:
        from common.ui import ui_title_font as shared

        return shared()
    except ImportError:
        return ui_font(15, "bold")


def load_session(path: Path) -> dict[str, str]:
    _add_common()
    try:
        from common.session import load_session as shared

        return shared(path)
    except ImportError:
        data: dict[str, str] = {}
        if not path.is_file():
            return data
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
        return data


def save_session(path: Path, data: dict[str, str]) -> None:
    _add_common()
    try:
        from common.session import save_session as shared

        shared(path, data)
        return
    except ImportError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{key}={value}\n" for key, value in data.items()), encoding="utf-8")


def default_recipes_root() -> str:
    try:
        from config import load_settings

        root = load_settings().recipes_root
        return str(root)
    except Exception:
        return ""


def _checked_tree():
    _add_common()
    try:
        from common.checked_tree import YES, CheckedTree

        return YES, CheckedTree
    except ImportError:
        from checked_tree import YES, CheckedTree

        return YES, CheckedTree


PREVIEW_MAX_PARAS = 200
PREVIEW_MAX_CHARS = 40000
PDF_PREVIEW_DPI = 144
PDF_PAGE_DPI = 180
MAX_RECIPE_PAGES = 40
MIN_EMBED_SIDE = 120
VIDEO_SUFFIXES = (".mp4", ".webm", ".mov", ".m4v", ".3gp")
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp")
WD_FORMAT_PDF = 17


def readable_title(name: str) -> str:
    return Path(name).stem.replace("_", " ").replace("-", " ").strip().title()


def safe_rel(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> str:
    return os.path.relpath(str(path), str(root)).replace("\\", "/")


def ensure_image_dir(root_dir: Path, keep: bool) -> Path:
    image_dir = root_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    if not keep:
        for child in image_dir.iterdir():
            try:
                if child.is_file() or child.is_symlink():
                    child.unlink(missing_ok=True)
            except Exception as exc:
                logging.warning("Konnte altes Bild nicht entfernen: %s (%s)", child, exc)
    return image_dir


def unique_basename(source_path: Path) -> str:
    h = hashlib.md5(str(source_path).encode("utf-8")).hexdigest()[:8]
    return f"{source_path.stem}_{h}"


def _save_and_resize_if_needed(out_path: Path, max_width: int = THUMB_MAX_WIDTH) -> Path:
    if Image is None:
        return out_path
    try:
        with Image.open(out_path) as im:
            im.load()
            if im.width > max_width:
                ratio = max_width / float(im.width)
                new_size = (max_width, int(im.height * ratio))
                im = im.resize(new_size, Image.LANCZOS)
                im.save(out_path)
    except Exception as exc:
        logging.debug("Resize übersprungen (%s)", exc)
    return out_path

# ---------------------- DOCX: Text- und Bildvorschau ------------------------

def extract_docx_image(docx_path: Path, output_name: str, image_dir: Path) -> Path | None:
    try:
        with zipfile.ZipFile(docx_path, "r") as zf:
            for name in zf.namelist():
                if name.startswith("word/media/") and not name.endswith("/"):
                    ext = Path(name).suffix or ".bin"
                    out_path = image_dir / f"{output_name}{ext}"
                    with zf.open(name) as src, open(out_path, "wb") as dst:
                        dst.write(src.read())
                    return _save_and_resize_if_needed(out_path)
    except Exception as exc:
        logging.warning("DOCX-Extraktion fehlgeschlagen: %s (%s)", docx_path, exc)
    return None


def _docx_paragraphs(docx_path: Path) -> list[str]:
    """Entnimmt Klartext-Absätze aus word/document.xml (ohne python-docx)."""
    try:
        with zipfile.ZipFile(docx_path, "r") as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception as exc:
        logging.debug("DOCX-Text konnte nicht gelesen werden: %s (%s)", docx_path, exc)
        return []

    # Sehr einfache Extraktion: w:p … w:t-Texte sammeln (ohne komplexe Formatierung)
    try:
        import re
        paras: list[str] = []
        for p in re.findall(r"<w:p[\s\S]*?</w:p>", xml):
            texts = re.findall(r"<w:t[^>]*>([\s\S]*?)</w:t>", p)
            if texts:
                para = "".join(texts)
                # XML-Entities & Soft-Hyphens bereinigen
                para = (para
                        .replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
                        .replace("\u00ad", ""))
                paras.append(para)
        paras = [x.strip() for x in paras if x.strip()]
        return paras
    except Exception as exc:
        logging.debug("DOCX-Regex fehlgeschlagen: %s", exc)
        return []


def build_docx_preview_html(docx_path: Path) -> str:
    paras = _docx_paragraphs(docx_path)
    if not paras:
        return "<em>Keine DOCX-Vorschau verfügbar.</em>"
    out: list[str] = []
    char_count = 0
    for i, p in enumerate(paras):
        if i >= PREVIEW_MAX_PARAS or char_count >= PREVIEW_MAX_CHARS:
            break
        esc = html.escape(p)
        out.append(f"<p>{esc}</p>")
        char_count += len(p)
    return "\n".join(out)

# ------------------------ PDF + DOCX → PDF ----------------------------------

def _ps_single(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "''") + "'"


def _soffice_path() -> Path | None:
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return Path(found)
    for candidate in (
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    ):
        if candidate.is_file():
            return candidate
    return None


def _word_to_pdf(docx_path: Path, pdf_path: Path) -> bool:
    script = Path(tempfile.gettempdir()) / "media_overview_docx2pdf.ps1"
    script.write_text(
        "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                "$word = New-Object -ComObject Word.Application",
                "$word.Visible = $false",
                "$word.DisplayAlerts = 0",
                "try {",
                f"  $doc = $word.Documents.Open({_ps_single(docx_path)}, $false, $true)",
                f"  $doc.SaveAs2({_ps_single(pdf_path)}, {WD_FORMAT_PDF})",
                "  $doc.Close($false)",
                "} finally {",
                "  $word.Quit() | Out-Null",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logging.debug("Word-PDF übersprungen: %s", exc)
        return False
    if completed.returncode != 0:
        logging.debug("Word-PDF fehlgeschlagen: %s", (completed.stderr or completed.stdout)[:400])
        return False
    return pdf_path.is_file()


def _libreoffice_to_pdf(docx_path: Path, pdf_path: Path) -> bool:
    soffice = _soffice_path()
    if soffice is None:
        return False
    try:
        completed = subprocess.run(
            [
                str(soffice),
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(docx_path.parent),
                str(docx_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logging.debug("LibreOffice-PDF übersprungen: %s", exc)
        return False
    produced = docx_path.with_suffix(".pdf")
    if completed.returncode != 0 or not produced.is_file():
        logging.debug("LibreOffice-PDF fehlgeschlagen: %s", (completed.stderr or completed.stdout)[:400])
        return False
    if produced.resolve() != pdf_path.resolve():
        try:
            shutil.move(str(produced), str(pdf_path))
        except OSError:
            return produced.is_file()
    return pdf_path.is_file()


def convert_docx_to_pdf(docx_path: Path) -> Path | None:
    pdf_path = docx_path.with_suffix(".pdf")
    if pdf_path.is_file():
        return pdf_path
    logging.info("Erzeuge PDF aus DOCX: %s", docx_path.name)
    if _word_to_pdf(docx_path, pdf_path):
        logging.info("PDF per Word: %s", pdf_path.name)
        return pdf_path
    if _libreoffice_to_pdf(docx_path, pdf_path):
        logging.info("PDF per LibreOffice: %s", pdf_path.name)
        return pdf_path
    logging.warning(
        "Keine PDF aus %s — Word oder LibreOffice wird für den Druck nach PDF gebraucht.",
        docx_path.name,
    )
    return None


def find_or_create_pdf(dirpath: Path, filenames: list[str]) -> Path | None:
    pdfs = sorted(name for name in filenames if name.lower().endswith(".pdf"))
    if pdfs:
        return dirpath / pdfs[0]
    docxs = sorted(name for name in filenames if name.lower().endswith(".docx"))
    if not docxs:
        return None
    return convert_docx_to_pdf(dirpath / docxs[0])


def extract_pdf_image(pdf_path: Path, output_name: str, image_dir: Path) -> Path | None:
    if fitz is None:
        logging.debug("PyMuPDF nicht verfügbar")
        return None
    doc = None
    try:
        doc = fitz.open(pdf_path)
        best_xref = None
        best_area = 0
        for page in doc:
            for image in page.get_images(full=True):
                xref, _smask, width, height = image[0], image[1], image[2], image[3]
                if min(width, height) < MIN_EMBED_SIDE:
                    continue
                area = width * height
                if area > best_area:
                    best_area = area
                    best_xref = xref
        if best_xref is not None:
            extracted = doc.extract_image(best_xref)
            image_bytes = extracted.get("image")
            ext = extracted.get("ext", "png")
            if image_bytes:
                out_path = image_dir / f"{output_name}.{ext}"
                out_path.write_bytes(image_bytes)
                return _save_and_resize_if_needed(out_path)
        if len(doc) > 0:
            page = doc[0]
            pix = page.get_pixmap(dpi=PDF_PREVIEW_DPI, alpha=False)
            out_path = image_dir / f"{output_name}.png"
            pix.save(out_path)
            return _save_and_resize_if_needed(out_path)
    except Exception as exc:
        logging.warning("PDF-Extraktion fehlgeschlagen: %s (%s)", pdf_path, exc)
    finally:
        if doc is not None:
            doc.close()
    return None


def render_pdf_pages(pdf_path: Path, output_name: str, image_dir: Path) -> list[Path]:
    if fitz is None:
        return []
    pages: list[Path] = []
    doc = None
    try:
        doc = fitz.open(pdf_path)
        for index, page in enumerate(doc):
            if index >= MAX_RECIPE_PAGES:
                break
            out_path = image_dir / f"{output_name}_p{index + 1}.png"
            if not out_path.is_file():
                pix = page.get_pixmap(dpi=PDF_PAGE_DPI, alpha=False)
                pix.save(out_path)
                _save_and_resize_if_needed(out_path, PAGE_MAX_WIDTH)
            pages.append(out_path)
    except Exception as exc:
        logging.warning("PDF-Seiten nicht gerendert: %s (%s)", pdf_path, exc)
    finally:
        if doc is not None:
            doc.close()
    return pages


def pdf_text_full(pdf_path: Path) -> str:
    if fitz is None:
        return ""
    doc = None
    try:
        doc = fitz.open(pdf_path)
        chunks: list[str] = []
        for page in doc:
            text = page.get_text("text") or ""
            text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
            if text:
                chunks.append(text)
        return "\n\n".join(chunks)
    except Exception:
        return ""
    finally:
        if doc is not None:
            doc.close()

# --------------------------- Video-Thumbnail --------------------------------

def _video_duration_seconds(cap) -> float | None:
    try:
        fps = cap.get(getattr(cv2, "CAP_PROP_FPS", 5.0)) or 0.0
        frame_count = cap.get(getattr(cv2, "CAP_PROP_FRAME_COUNT", 0)) or 0.0
        if fps > 0 and frame_count > 0:
            return float(frame_count / fps)
    except Exception:
        pass
    return None


def extract_mp4_thumbnail(mp4_path: Path, output_name: str, image_dir: Path, seconds: float) -> Path | None:
    if cv2 is None:
        logging.debug("OpenCV nicht verfügbar")
        return None
    try:
        cap = cv2.VideoCapture(str(mp4_path))
        if not cap.isOpened():
            logging.warning("Video nicht lesbar: %s", mp4_path)
            return None
        dur = _video_duration_seconds(cap)
        ts = max(0.0, min(seconds, dur if dur else seconds))
        cap.set(getattr(cv2, "CAP_PROP_POS_MSEC", 0), ts * 1000.0)
        ok, frame = cap.read()
        cap.release()
        if ok and frame is not None:
            out_path = image_dir / f"{output_name}.jpg"
            cv2.imwrite(str(out_path), frame)
            return _save_and_resize_if_needed(out_path)
    except Exception as exc:
        logging.warning("MP4-Thumbnail fehlgeschlagen: %s (%s)", mp4_path, exc)
    return None

# ------------------------------ Datenmodell ---------------------------------

@dataclasses.dataclass
class Tile:
    title: str
    image_path: Path
    folder_uri: str
    mp4_rel: Optional[str]
    preview_html: str
    kind: str = "image"
    pdf_rel: Optional[str] = None


def _video_tag(mp4_rel: str, poster_rel: str | None = None) -> str:
    poster = f' poster="{html.escape(poster_rel, quote=True)}"' if poster_rel else ""
    return (
        f'<video class="recipe-video" controls preload="metadata" playsinline '
        f'src="{html.escape(mp4_rel, quote=True)}"{poster}></video>'
    )


def build_recipe_preview(
    *,
    pdf_path: Path | None,
    docx_path: Path | None,
    mp4_rel: str | None,
    image_dir: Path,
    root_dir: Path,
    poster_rel: str | None,
) -> str:
    parts: list[str] = []
    if mp4_rel:
        parts.append(_video_tag(mp4_rel, poster_rel))
    if pdf_path is not None:
        outname = unique_basename(pdf_path)
        pages = render_pdf_pages(pdf_path, outname, image_dir)
        pdf_rel = html.escape(safe_rel(pdf_path, root_dir), quote=True)
        if pages:
            images = "\n".join(
                f'<img src="{html.escape(safe_rel(page, root_dir), quote=True)}" alt="Seite {index + 1}">'
                for index, page in enumerate(pages)
            )
            note = (
                '<p class="muted">Nur die ersten Seiten hier — der Rest steht in der PDF. / ここは先頭ページ。続きはPDF。</p>'
                if len(pages) >= MAX_RECIPE_PAGES
                else ""
            )
            parts.append(f'<div class="pages">{images}</div>{note}')
        else:
            text = pdf_text_full(pdf_path)
            if text:
                parts.append(f'<div class="excerpt">{html.escape(text)}</div>')
            parts.append(
                f'<embed class="recipe-frame" src="{pdf_rel}" type="application/pdf">'
            )
        parts.append(
            f'<p><a class="act primary" href="{pdf_rel}" target="_blank" rel="noopener">PDF öffnen · PDFを開く</a></p>'
        )
    elif docx_path is not None:
        parts.append(build_docx_preview_html(docx_path))
    elif not mp4_rel:
        parts.append('<p class="muted">Kein PDF oder DOCX in diesem Ordner. / このフォルダにPDFもDOCXもありません。</p>')
    return "\n".join(parts)


def choose_thumbnail_for_dir(
    dirpath: Path,
    filenames: list[str],
    root_dir: Path,
    image_dir: Path,
    thumb_sec: float,
) -> Tile | None:
    docx_files = sorted(name for name in filenames if name.lower().endswith(".docx"))
    pdf_files = sorted(name for name in filenames if name.lower().endswith(".pdf"))
    video_files = sorted(name for name in filenames if name.lower().endswith(VIDEO_SUFFIXES))

    if pdf_files:
        title = readable_title(pdf_files[0])
    elif docx_files:
        title = readable_title(docx_files[0])
    elif video_files:
        title = readable_title(video_files[0])
    else:
        title = readable_title(dirpath.name)

    pdf_path = find_or_create_pdf(dirpath, filenames)
    docx_path = dirpath / docx_files[0] if docx_files else None
    mp4_rel = safe_rel(dirpath / video_files[0], root_dir) if video_files else None

    final_image: Path | None = None
    kind = "image"

    if pdf_path is not None:
        kind = "pdf"
        outname = unique_basename(pdf_path)
        final_image = extract_pdf_image(pdf_path, outname, image_dir)
        if final_image is None and docx_path is not None:
            final_image = extract_docx_image(docx_path, unique_basename(docx_path), image_dir)
    elif docx_path is not None:
        kind = "docx"
        final_image = extract_docx_image(docx_path, unique_basename(docx_path), image_dir)
    elif video_files:
        kind = "video"
    else:
        image_files = sorted(name for name in filenames if name.lower().endswith(IMAGE_SUFFIXES))
        if image_files:
            src = dirpath / image_files[0]
            out = image_dir / f"{unique_basename(src)}{Path(image_files[0]).suffix}"
            try:
                if Image is not None:
                    with Image.open(src) as im:
                        im.load()
                        im.save(out)
                else:
                    out.write_bytes(src.read_bytes())
                final_image = _save_and_resize_if_needed(out)
            except Exception as exc:
                logging.warning("Bildkopie fehlgeschlagen: %s (%s)", src, exc)

    if final_image is None and video_files:
        final_image = extract_mp4_thumbnail(
            dirpath / video_files[0],
            unique_basename(dirpath / video_files[0]),
            image_dir,
            thumb_sec,
        )

    poster_rel = safe_rel(final_image, root_dir) if final_image else None
    preview_html = build_recipe_preview(
        pdf_path=pdf_path,
        docx_path=None if pdf_path is not None else docx_path,
        mp4_rel=mp4_rel,
        image_dir=image_dir,
        root_dir=root_dir,
        poster_rel=poster_rel,
    )

    if final_image is None:
        if pdf_path is None and mp4_rel is None:
            return None
        placeholder = image_dir / f"{unique_basename(dirpath)}_card.svg"
        if not placeholder.is_file():
            placeholder.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">'
                '<rect width="100%" height="100%" fill="#ece4da"/>'
                "</svg>",
                encoding="utf-8",
            )
        final_image = placeholder

    return Tile(
        title=title,
        image_path=final_image,
        folder_uri=dirpath.as_uri(),
        mp4_rel=mp4_rel,
        preview_html=preview_html,
        kind=kind,
        pdf_rel=safe_rel(pdf_path, root_dir) if pdf_path else None,
    )

# ------------------------------ HTML-Renderer -------------------------------

KIND_LABEL = {"pdf": "PDF", "docx": "DOCX", "video": "Video", "image": "Bild"}

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
__FONT_CSS__
:root {
  --bg: #f3eee6;
  --ink: #2a211b;
  --muted: #7a6e64;
  --card: #fffdf9;
  --line: #e4d8cc;
  --accent: #c45c26;
  --accent-ink: #fff;
  --shadow: 0 10px 28px rgba(62, 39, 22, .08);
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body {
  background:
    radial-gradient(900px 380px at 8% -12%, #fbe6d1 0%, transparent 55%),
    radial-gradient(700px 320px at 110% 0%, #eadccb 0%, transparent 50%),
    var(--bg);
  color: var(--ink);
  min-height: 100vh;
}
.wrap { max-width: 1180px; margin: 0 auto; padding: 28px 22px 64px; }
.hero { margin-bottom: 18px; }
.hero h1 { font-size: 1.85rem; margin: 0 0 8px; font-weight: 700; letter-spacing: 0; }
.hero p { margin: 0; color: var(--muted); max-width: 62ch; }
.toolbar {
  position: sticky; top: 10px; z-index: 6;
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  background: rgba(255, 253, 249, .94);
  border: 1px solid var(--line); border-radius: 16px;
  padding: 10px; margin-bottom: 22px; box-shadow: var(--shadow);
}
.toolbar input {
  flex: 1 1 240px; border: 1px solid var(--line); border-radius: 12px;
  padding: 11px 14px; font: inherit; background: #fff;
}
.toolbar input:focus { outline: 2px solid #e8b496; border-color: var(--accent); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chips button, .card .act {
  border: 1px solid var(--line); background: #fff; color: var(--ink);
  border-radius: 999px; padding: 8px 12px; font: inherit; cursor: pointer;
}
.chips button:hover, .card .act:hover { border-color: var(--accent); }
.chips button[aria-pressed="true"] {
  background: var(--accent); color: var(--accent-ink); border-color: var(--accent);
}
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 18px; }
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: 18px;
  overflow: hidden; box-shadow: var(--shadow); display: flex; flex-direction: column;
  transition: transform .15s ease, box-shadow .15s ease;
}
.card:hover { transform: translateY(-4px); box-shadow: 0 18px 40px rgba(62, 39, 22, .14); }
.thumb-wrap { position: relative; width: 100%; aspect-ratio: 4/3; background: #ece4da; }
.thumb {
  position: absolute; inset: 0; display: block; width: 100%; height: 100%;
  border: 0; padding: 0; cursor: zoom-in; background: transparent;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.inline-video {
  width: 100%; height: 100%; object-fit: contain; display: block;
  cursor: pointer; background: #1c1815;
}
.badge {
  position: absolute; left: 10px; top: 10px; color: #fff; z-index: 2;
  font-size: .72rem; letter-spacing: .04em; padding: 4px 8px; border-radius: 999px;
  background: rgba(43,34,28,.86); pointer-events: none;
}
.kind-pdf { background: #8b3a1f; }
.kind-docx { background: #1f4e8b; }
.kind-video { background: #c45c26; }
.kind-image { background: #3d6b3a; }
.play {
  position: absolute; left: 50%; top: 50%; width: 56px; height: 56px; margin: 0;
  transform: translate(-50%, -50%); border-radius: 50%;
  border: 0; z-index: 3; cursor: pointer;
  background: rgba(196,92,38,.94); color: #fff; display: grid; place-items: center; font-size: 1.2rem;
  box-shadow: 0 8px 20px rgba(196,92,38,.35);
}
.play:hover { transform: translate(-50%, -50%) scale(1.06); }
.meta { padding: 14px 14px 16px; display: flex; flex-direction: column; gap: 10px; flex: 1; }
.meta h2 { font-size: 1.02rem; margin: 0; line-height: 1.3; }
.actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: auto; }
.card .act { text-decoration: none; font-size: .82rem; padding: 6px 10px; }
.card .act.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
.empty { text-align: center; color: var(--muted); padding: 52px 12px; }
.hidden { display: none !important; }
.modal {
  position: fixed; inset: 0; background: rgba(32, 22, 16, .58); display: none;
  align-items: center; justify-content: center; padding: 12px; z-index: 20;
}
.modal.open { display: flex; }
.modal-box {
  background: var(--card); width: min(980px, 96vw); max-height: 94vh; overflow: auto;
  border-radius: 18px; box-shadow: 0 24px 60px rgba(0,0,0,.28);
}
.modal-head {
  position: sticky; top: 0; background: var(--card); z-index: 1;
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 18px; border-bottom: 1px solid var(--line);
}
.modal-head h2 { margin: 0; font-size: 1.1rem; }
.modal-close {
  border: 0; background: #f3eee6; width: 36px; height: 36px; border-radius: 50%;
  font-size: 1.35rem; cursor: pointer; color: var(--muted); line-height: 1;
}
.modal-content { padding: 18px; }
.modal-content img { max-width: 100%; height: auto; border-radius: 12px; }
.modal-content p, .excerpt { line-height: 1.55; white-space: pre-wrap; }
.pages img { width: 100%; height: auto; display: block; margin: 0 0 14px; border-radius: 10px; box-shadow: var(--shadow); image-rendering: auto; }
.recipe-video { width: 100%; max-height: 420px; border-radius: 12px; background: #1c1815; margin-bottom: 16px; }
.recipe-frame { width: 100%; height: 75vh; border: 1px solid var(--line); border-radius: 12px; }
.muted { color: var(--muted); }
footer { margin-top: 28px; color: var(--muted); font-size: .82rem; }
@media (max-width: 640px) {
  .hero h1 { font-size: 1.4rem; }
  .grid { grid-template-columns: 1fr 1fr; gap: 12px; }
  .toolbar { top: 0; border-radius: 0 0 14px 14px; }
}
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <h1>__TITLE__</h1>
    <p>Suche nach Namen, filtere nach Dateityp. ▶ spielt das Video auf der Karte.
      Klick aufs Bild zeigt das ganze Rezept.<br>
      名前で検索、種類で絞り込み。▶でカード上再生。画像クリックでレシピ全体。
      <strong id="shown">__COUNT__</strong> von __COUNT__ sichtbar / 件表示。</p>
  </header>
  <div class="toolbar">
    <input id="q" type="search" placeholder="Suchen… / 検索" autocomplete="off" autofocus>
    <div class="chips" role="group" aria-label="Filter">
      <button type="button" data-kind="all" data-label="Alle · すべて" aria-pressed="true">Alle · すべて</button>
      <button type="button" data-kind="pdf" data-label="PDF">PDF</button>
      <button type="button" data-kind="docx" data-label="DOCX">DOCX</button>
      <button type="button" data-kind="video" data-label="Video">Video</button>
      <button type="button" data-kind="image" data-label="Bild · 画像">Bild · 画像</button>
    </div>
  </div>
  <div class="grid" id="grid">__CARDS__</div>
  __EMPTY__
  <p class="empty hidden" id="none">Keine Treffer. Suche oder Filter anpassen. / 該当なし。検索かフィルタを変えてください。</p>
  <footer>▶ Video auf der Karte · Klick aufs Bild = ganzes Rezept · Esc schließt · / Suche<br>
    ▶カード上再生 · 画像クリックでレシピ全体 · Escで閉じる · / で検索</footer>
</div>
<div class="modal" id="modal" role="dialog" aria-modal="true" aria-hidden="true" aria-labelledby="modalTitle">
  <div class="modal-box">
    <div class="modal-head">
      <h2 id="modalTitle">Vorschau</h2>
      <button class="modal-close" id="modalClose" type="button" aria-label="Schließen">×</button>
    </div>
    <div class="modal-content" id="modalContent"></div>
  </div>
</div>
<script>
(function(){
  const q = document.getElementById('q');
  const grid = document.getElementById('grid');
  const shown = document.getElementById('shown');
  const none = document.getElementById('none');
  const modal = document.getElementById('modal');
  const content = document.getElementById('modalContent');
  const titleEl = document.getElementById('modalTitle');
  let kind = 'all';
  function labelChips(){
    const counts = {all: 0, pdf: 0, docx: 0, video: 0, image: 0};
    grid.querySelectorAll('.card').forEach(card => {
      counts.all += 1;
      const k = card.dataset.kind;
      if (k && k !== 'video' && k in counts) counts[k] += 1;
      if (card.dataset.video === '1' || k === 'video') counts.video += 1;
    });
    document.querySelectorAll('.chips button').forEach(btn => {
      const k = btn.dataset.kind;
      btn.textContent = btn.dataset.label + ' · ' + (counts[k] || 0);
    });
  }
  function apply(){
    const needle = (q.value || '').trim().toLowerCase();
    let n = 0;
    const cards = grid.querySelectorAll('.card');
    cards.forEach(card => {
      const matchKind = kind === 'all'
        || (kind === 'video' ? card.dataset.video === '1' : card.dataset.kind === kind);
      const matchText = !needle || (card.dataset.title || '').includes(needle);
      const ok = matchKind && matchText;
      card.classList.toggle('hidden', !ok);
      card.setAttribute('aria-hidden', ok ? 'false' : 'true');
      if (ok) n += 1;
    });
    shown.textContent = n;
    none.classList.toggle('hidden', n > 0 || cards.length === 0);
  }
  q.addEventListener('input', apply);
  document.querySelectorAll('.chips button').forEach(btn => {
    btn.addEventListener('click', () => {
      kind = btn.dataset.kind;
      document.querySelectorAll('.chips button').forEach(b => b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'));
      apply();
    });
  });
  function pauseAll(){
    document.querySelectorAll('video').forEach(v => { try { v.pause(); } catch (err) {} });
  }
  function playOnCard(btn){
    const card = btn.closest('.card');
    const wrap = card ? card.querySelector('.thumb-wrap') : null;
    const src = btn.getAttribute('data-play');
    if (!wrap || !src) return;
    pauseAll();
    wrap.innerHTML = '<video class="inline-video" src="' + src.replace(/"/g, '&quot;') + '" controls autoplay playsinline></video>';
  }
  function openPreview(id, name){
    const tpl = document.getElementById(id);
    if (!tpl) return;
    pauseAll();
    titleEl.textContent = name || 'Vorschau';
    content.innerHTML = tpl.innerHTML;
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
  }
  function close(){
    pauseAll();
    modal.classList.remove('open');
    content.innerHTML = '';
    titleEl.textContent = 'Vorschau';
    modal.setAttribute('aria-hidden', 'true');
  }
  document.addEventListener('click', (e) => {
    const playBtn = e.target.closest('[data-play]');
    if (playBtn){
      e.preventDefault();
      e.stopPropagation();
      playOnCard(playBtn);
      return;
    }
    const prev = e.target.closest('[data-prev]');
    if (prev){
      e.preventDefault();
      openPreview(prev.getAttribute('data-prev'), prev.getAttribute('data-title') || '');
      return;
    }
    if (e.target === modal || e.target.id === 'modalClose') close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
    const active = document.activeElement;
    if (e.key === '/' && active !== q && (!active || active.tagName !== 'INPUT')) {
      e.preventDefault();
      q.focus();
      q.select();
    }
  });
  labelChips();
  apply();
})();
</script>
</body>
</html>
"""


def render_html(folder_name: str, tiles: list[Tile], root_dir: Path) -> str:
    cards: list[str] = []
    for idx, tile in enumerate(tiles):
        rel_img = html.escape(safe_rel(tile.image_path, root_dir), quote=True)
        title = html.escape(tile.title)
        kind = html.escape(tile.kind)
        label = KIND_LABEL.get(tile.kind, tile.kind.upper())
        has_video = "1" if tile.mp4_rel else "0"
        play = ""
        video_btn = ""
        if tile.mp4_rel:
            src = html.escape(tile.mp4_rel, quote=True)
            play = (
                f'<button class="play" type="button" data-play="{src}" '
                f'aria-label="Video abspielen">▶</button>'
            )
            video_btn = f'<button class="act" type="button" data-play="{src}">Video</button>'
        cards.append(
            f'''<article class="card" data-kind="{kind}" data-video="{has_video}" data-title="{html.escape(tile.title.casefold())}">
  <div class="thumb-wrap">
    <button class="thumb" type="button" data-prev="prev_{idx}" data-title="{title}">
      <img src="{rel_img}" alt="">
    </button>
    <span class="badge kind-{kind}">{label}</span>
    {play}
  </div>
  <div class="meta">
    <h2>{title}</h2>
    <div class="actions">
      <button class="act primary" type="button" data-prev="prev_{idx}" data-title="{title}">Rezept · レシピ</button>
      <a class="act folder-link" href="{html.escape(tile.folder_uri, quote=True)}" target="_blank" rel="noopener">Ordner · フォルダ</a>
      {video_btn}
    </div>
  </div>
  <template id="prev_{idx}">{tile.preview_html}</template>
</article>'''
        )
    empty = "" if tiles else '<p class="empty">Keine Kacheln in diesem Ordner. / このフォルダにカードがありません。</p>'
    return (
        HTML_PAGE.replace("__TITLE__", html.escape(folder_name))
        .replace("__FONT_CSS__", html_font_css())
        .replace("__COUNT__", str(len(tiles)))
        .replace("__CARDS__", "\n".join(cards))
        .replace("__EMPTY__", empty)
    )


# --------------------------------- Runner -----------------------------------

def process_root(
    root_dir: Path,
    keep_images: bool,
    thumb_sec: float,
    only: list[str] | None = None,
) -> list[Path]:
    image_dir = ensure_image_dir(root_dir, keep=keep_images or only is not None)
    created_files: list[Path] = []
    wanted = {name.lower() for name in only} if only is not None else None
    for entry in os.scandir(root_dir):
        if not entry.is_dir():
            continue
        if Path(entry.path) == image_dir:
            continue
        if entry.name.lower() in IGNORE_DIR_NAMES:
            continue
        if wanted is not None and entry.name.lower() not in wanted:
            continue
        subfolder_path = Path(entry.path)
        folder_name = subfolder_path.name
        tiles: list[Tile] = []
        for dirpath, dirnames, filenames in os.walk(subfolder_path):
            dirnames[:] = [d for d in dirnames if d.lower() not in IGNORE_DIR_NAMES]
            p = Path(dirpath)
            if p.resolve() == image_dir.resolve():
                continue
            tile = choose_thumbnail_for_dir(p, list(filenames), root_dir=root_dir, image_dir=image_dir, thumb_sec=thumb_sec)
            if tile:
                tiles.append(tile)
        html_text = render_html(folder_name, tiles, root_dir)
        out_html = root_dir / f"{folder_name}.html"
        try:
            out_html.write_text(html_text, encoding="utf-8")
            created_files.append(out_html)
            logging.info("HTML erstellt: %s (%d Kacheln)", out_html, len(tiles))
        except Exception as exc:
            logging.error("Konnte HTML nicht schreiben: %s (%s)", out_html, exc)
    return created_files


# --------------------------------- GUI -----------------------------------

SESSION = Path(__file__).resolve().parent / "local" / "media_overview.last"
SESSION.parent.mkdir(parents=True, exist_ok=True)

BG = "#1c1815"
CARD = "#2a241f"
CARD_HI = "#352c26"
TEXT = "#f6f0e8"
MUTED = "#b7a89b"
ACCENT = "#d36b38"
LINE = "#3f352d"


def list_targets(root_dir: Path) -> list[str]:
    names: list[str] = []
    if not root_dir.is_dir():
        return names
    for entry in os.scandir(root_dir):
        if not entry.is_dir():
            continue
        if entry.name.lower() in IGNORE_DIR_NAMES or entry.name.lower() == "images":
            continue
        names.append(entry.name)
    return sorted(names, key=str.casefold)


def init_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )


def open_path(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            import webbrowser

            webbrowser.open(path.as_uri())
    except Exception:
        pass


def html_path_for(root_dir: Path, name: str) -> Path:
    return root_dir / f"{name}.html"


class StatCard(tk.Frame if tk is not None else object):
    def __init__(self, parent: tk.Widget, title: str) -> None:
        super().__init__(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        self.value = tk.Label(self, text="0", bg=CARD, fg=ACCENT, font=ui_font(18, "bold"))
        self.value.pack(anchor="w", padx=12, pady=(8, 0))
        tk.Label(self, text=title, bg=CARD, fg=MUTED, font=ui_small_font()).pack(anchor="w", padx=12, pady=(2, 8))

    def set(self, number: int) -> None:
        self.value.configure(text=str(number))


class MediaOverviewApp:
    def __init__(self, root: tk.Tk, folder: str = "") -> None:
        YES, CheckedTree = _checked_tree()
        try:
            from common.launch import hide_owned_console

            hide_owned_console()
        except ImportError:
            pass
        try:
            from common.ui import bind_responsive_ui, fit_window
        except ImportError:
            def bind_responsive_ui(_root, **_kwargs) -> None:
                return None

            def fit_window(_root, **_kwargs) -> None:
                return None

        self._yes = YES
        self._save_session = save_session
        saved = load_session(SESSION)
        self.root = root
        root.title("Media Overview")
        root.geometry("1180x820")
        root.minsize(880, 620)
        root.configure(bg=BG)
        self.folder = tk.StringVar(value=folder or saved.get("folder") or default_recipes_root())
        self.keep_images = tk.BooleanVar(value=saved.get("keep_images", "1") != "0")
        self.open_when_done = tk.BooleanVar(value=saved.get("open_when_done", "1") != "0")
        self.thumb_sec = tk.StringVar(value=saved.get("thumb_sec", "5"))
        self.filter = tk.StringVar()
        self._unchecked = {part for part in saved.get("unchecked", "").split("|") if part}
        self._busy = False
        self.names: list[str] = []
        self.checks: dict[str, bool] = {}
        self._root_dir: Path | None = None
        self._created: list[Path] = []
        self._style()

        tk.Frame(root, bg=ACCENT, height=2).pack(fill="x")

        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(header, text="Media Overview", bg=BG, fg=TEXT, font=ui_title_font()).pack(anchor="w")
        self.blurb = tk.Label(
            header,
            text=explain(
                "Reciplate-Ergänzung: den Rezepte-Root wählen (Kochen/Backen) oder einen Abschnitt. "
                "Angehakte Ordner werden zur Galerie — ▶ spielt das Video, Klick zeigt das ganze Rezept. "
                "Nur DOCX: einmal PDF daneben (Word oder LibreOffice). ignore/ raus, Thumbs in images/.",
                "Reciplateの補助: レシピのルート（Kochen/Backen）かセクションを選ぶ。"
                "チェックしたフォルダがギャラリーになる。▶で動画、クリックでレシピ全体。"
                "DOCXだけなら隣にPDFを一度作る。ignore/は除外、サムネは images/。",
                "Reciplate companion: pick the recipe library root (Kochen/Backen) or one section. "
                "Checked folders become galleries — ▶ plays the video, click for the whole recipe. "
                "DOCX-only folders get a PDF printed beside them once. ignore/ is skipped; thumbs go in images/.",
            ),
            bg=BG,
            fg=MUTED,
            font=ui_small_font(),
            justify="left",
            wraplength=1080,
        )
        self.blurb.pack(anchor="w", pady=(3, 0))

        folder_card = tk.Frame(root, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        folder_card.pack(fill="x", padx=12, pady=4)
        folder_inner = tk.Frame(folder_card, bg=CARD)
        folder_inner.pack(fill="x", padx=10, pady=6)
        tk.Label(folder_inner, text="Übergeordneter Ordner", bg=CARD, fg=MUTED, font=ui_small_font()).pack(anchor="w")
        folder_row = tk.Frame(folder_inner, bg=CARD)
        folder_row.pack(fill="x", pady=(6, 0))
        folder_entry = tk.Entry(
            folder_row,
            textvariable=self.folder,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=ACCENT,
            font=ui_font(),
        )
        folder_entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))
        folder_entry.bind("<Return>", lambda _event: self.preview())
        ttk.Button(folder_row, text="Durchsuchen…", command=self.browse).pack(side="left")
        ttk.Button(folder_row, text="Öffnen", command=self.open_parent).pack(side="left", padx=(6, 0))

        opts = tk.Frame(root, bg=BG)
        opts.pack(fill="x", padx=12, pady=(0, 4))
        self._check(opts, "Alte Vorschaubilder behalten", self.keep_images).pack(side="left", padx=(0, 16))
        self._check(opts, "HTML danach öffnen", self.open_when_done).pack(side="left", padx=(0, 16))
        tk.Label(opts, text="Video bei Sekunde", bg=BG, fg=MUTED).pack(side="left", padx=(0, 6))
        sec = tk.Entry(
            opts,
            textvariable=self.thumb_sec,
            width=5,
            bg=CARD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=ACCENT,
        )
        sec.pack(side="left", ipady=3)

        stats = tk.Frame(root, bg=BG)
        stats.pack(fill="x", padx=12, pady=(0, 4))
        self.stat_folders = StatCard(stats, "Unterordner")
        self.stat_checked = StatCard(stats, "Angehakt")
        self.stat_html = StatCard(stats, "HTML vorhanden")
        self.stat_folders.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.stat_checked.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.stat_html.pack(side="left", fill="x", expand=True)

        tools = tk.Frame(root, bg=BG)
        tools.pack(fill="x", padx=12, pady=(2, 2))
        tk.Label(tools, text="Liste filtern", bg=BG, fg=MUTED).pack(side="left")
        filt = tk.Entry(
            tools,
            textvariable=self.filter,
            width=24,
            bg=CARD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=ACCENT,
            font=ui_font(),
        )
        filt.pack(side="left", padx=8, ipady=2)
        ttk.Button(tools, text="Aktualisieren", command=self.preview).pack(side="left", padx=4)
        ttk.Button(tools, text="Alle an", command=lambda: self._set_all(True)).pack(side="left", padx=4)
        ttk.Button(tools, text="Alle aus", command=lambda: self._set_all(False)).pack(side="left", padx=4)
        ttk.Button(tools, text="Umkehren", command=self._invert).pack(side="left", padx=4)
        ttk.Button(tools, text="HTML öffnen", command=self.open_selected).pack(side="left", padx=4)
        ttk.Button(tools, text="Ordner öffnen", command=self.open_folder_selected).pack(side="left", padx=4)
        self._run_btn = tk.Button(
            tools,
            text="Übersicht erstellen",
            command=self.start,
            bg=ACCENT,
            fg="#fff",
            activebackground="#e07a42",
            activeforeground="#fff",
            relief="flat",
            padx=14,
            pady=6,
            font=ui_font(None, "bold"),
            cursor="hand2",
        )
        self._run_btn.pack(side="right")

        self._hint = tk.Label(
            root,
            text="Klick auf „An“ wählt ab, Leertaste auch. Doppelklick öffnet HTML oder den Ordner. F5 aktualisiert, Strg+Enter erzeugt.\nAnをクリックで外す（Spaceも可）。ダブルクリックでHTMLかフォルダ。F5で更新、Ctrl+Enterで作成。",
            bg=BG,
            fg=MUTED,
            font=ui_small_font(),
            anchor="w",
            justify="left",
            wraplength=1080,
        )
        self._hint.pack(fill="x", padx=12, pady=(4, 0))

        self.list = CheckedTree(
            root,
            columns=("folder", "html", "state"),
            headings={"folder": "Unterordner", "html": "Datei", "state": "Stand"},
            widths={"folder": 280, "html": 260, "state": 120},
        )
        self.list.pack(fill="both", expand=True, padx=12, pady=4)
        self.list.tree.heading("pick", text="An")
        self.list.tree.column("#0", width=0, stretch=False)
        self.list.tree.tag_configure("neu", foreground=MUTED)
        self.list.tree.tag_configure("da", foreground=TEXT)
        self.list.tree.bind("<Double-1>", self._on_double)
        self.list.tree.bind("<ButtonRelease-1>", lambda _event: self._refresh_stats(), add="+")

        self.status = tk.Label(
            root,
            text="Word oder LibreOffice druckt fehlende PDFs. Pillow / PyMuPDF für Rezeptseiten, OpenCV für Videos.\nWordかLibreOfficeが不足PDFを印刷。Pillow / PyMuPDFはレシピページ、OpenCVは動画用。",
            bg=BG,
            fg=MUTED,
            font=ui_small_font(),
            anchor="w",
            wraplength=1080,
            justify="left",
        )
        self.status.pack(fill="x", padx=12, pady=(0, 8))

        self.filter.trace_add("write", lambda *_args: self._fill_list())
        root.bind("<F5>", lambda _event: self.preview())
        root.bind("<Control-Return>", lambda _event: self.start())
        bind_responsive_ui(root)
        root.protocol("WM_DELETE_WINDOW", self._close)
        saved_folder = Path(self.folder.get().strip().strip('"'))
        if saved_folder.is_dir():
            self.preview()
        root.after_idle(lambda: fit_window(root, min_width=1100, min_height=760, fill=0.68))

    def _check(self, parent: tk.Widget, text: str, variable: tk.BooleanVar) -> tk.Checkbutton:
        return tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            bg=BG,
            fg=TEXT,
            selectcolor=CARD,
            activebackground=BG,
            activeforeground=TEXT,
            highlightthickness=0,
            font=ui_font(),
        )

    def _style(self) -> None:
        try:
            from common.ui import apply_theme

            apply_theme(self.root)
        except ImportError:
            pass

    def _close(self) -> None:
        self._persist()
        self.root.destroy()

    def _sync_checks_from_tree(self) -> None:
        if not getattr(self, "list", None):
            return
        try:
            for iid in self.list._walk():
                name = self.list.tree.set(iid, "folder")
                if name:
                    self.checks[name] = self.list.tree.set(iid, "pick") == self._yes
        except tk.TclError:
            return

    def _selected_names(self) -> list[str]:
        self._sync_checks_from_tree()
        return [name for name in self.names if self.checks.get(name)]

    def _unchecked_names(self) -> list[str]:
        checked = set(self._selected_names())
        return [name for name in self.names if name not in checked]

    def _set_all(self, checked: bool) -> None:
        for name in self.names:
            self.checks[name] = checked
        self.list.set_all(checked)
        self._refresh_stats()

    def _invert(self) -> None:
        self._sync_checks_from_tree()
        for name in self.names:
            self.checks[name] = not self.checks.get(name, True)
        self._fill_list(skip_sync=True)
        self._refresh_stats()

    def _persist(self) -> None:
        try:
            self._save_session(
                SESSION,
                {
                    "folder": self.folder.get().strip(),
                    "keep_images": "1" if self.keep_images.get() else "0",
                    "open_when_done": "1" if self.open_when_done.get() else "0",
                    "thumb_sec": self.thumb_sec.get().strip(),
                    "unchecked": "|".join(self._unchecked_names()),
                },
            )
        except OSError:
            pass

    def _target(self, *, silent: bool = False) -> Path | None:
        target = Path(self.folder.get().strip().strip('"'))
        if not target.is_dir():
            if not silent:
                messagebox.showerror("Media Overview", "Bitte einen gültigen Ordner wählen.")
            return None
        return target

    def browse(self) -> None:
        chosen = filedialog.askdirectory(title="Übergeordneter Ordner mit Medien-Unterordnern")
        if chosen:
            self.folder.set(chosen)
            self.preview()

    def open_parent(self) -> None:
        target = self._target()
        if target is None:
            return
        open_path(target)

    def preview(self) -> None:
        target = self._target()
        if target is None:
            return
        self._sync_checks_from_tree()
        previous = dict(self.checks)
        self._root_dir = target
        self.names = list_targets(target)
        self.checks = {}
        for name in self.names:
            if name in previous:
                self.checks[name] = previous[name]
            else:
                self.checks[name] = name not in self._unchecked
        self._fill_list(skip_sync=True)
        existing = sum(1 for name in self.names if html_path_for(target, name).is_file())
        if self.names:
            self.status.configure(
                text=(
                    f"{len(self.names)} Unterordner, {existing} HTML schon da. "
                    "Haken weg = keine neue Datei. Doppelklick öffnet HTML, sonst den Ordner."
                )
            )
        else:
            self.status.configure(text="Keine Unterordner gefunden (außer ignore/ und images/).")
        self._refresh_stats()
        self._persist()

    def _fill_list(self, skip_sync: bool = False) -> None:
        if not getattr(self, "list", None) or self._root_dir is None:
            return
        if not skip_sync:
            self._sync_checks_from_tree()
        needle = self.filter.get().strip().casefold()
        self.list.clear()
        for index, name in enumerate(self.names):
            if needle and needle not in name.casefold():
                continue
            html_file = html_path_for(self._root_dir, name)
            exists = html_file.is_file()
            self.list.add(
                (name, html_file.name, "vorhanden" if exists else "neu"),
                iid=str(index),
                checked=self.checks.get(name, True),
            )
            self.list.tree.item(str(index), tags=("da" if exists else "neu",))
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        self._sync_checks_from_tree()
        existing = 0
        if self._root_dir is not None:
            existing = sum(1 for name in self.names if html_path_for(self._root_dir, name).is_file())
        self.stat_folders.set(len(self.names))
        self.stat_checked.set(sum(1 for name in self.names if self.checks.get(name)))
        self.stat_html.set(existing)

    def _row_names(self, event: tk.Event | None = None) -> list[str]:
        names: list[str] = []
        if event is not None:
            iid = self.list.tree.identify_row(event.y)
            if iid:
                name = self.list.tree.set(iid, "folder")
                if name:
                    return [name]
        focus = self.list.tree.focus()
        if focus:
            name = self.list.tree.set(focus, "folder")
            if name:
                names.append(name)
        for iid in self.list.tree.selection():
            name = self.list.tree.set(iid, "folder")
            if name and name not in names:
                names.append(name)
        return names

    def _on_double(self, event: tk.Event) -> None:
        if self.list.tree.identify_column(event.x) == "#1":
            return
        names = self._row_names(event)
        if names:
            self._open_names(names, quiet=True)

    def open_selected(self) -> None:
        names = self._row_names() or self._selected_names()[:1]
        self._open_names(names, quiet=False)

    def open_folder_selected(self) -> None:
        names = self._row_names() or self._selected_names()[:1]
        self._open_folders(names, quiet=False)

    def _open_names(self, names: list[str], *, quiet: bool) -> None:
        target = self._target(silent=quiet)
        if target is None or not names:
            if not quiet:
                messagebox.showinfo("Media Overview", "Nichts ausgewählt.")
            return
        opened = 0
        missing: list[str] = []
        for name in names[:8]:
            path = html_path_for(target, name)
            if path.is_file():
                open_path(path)
                opened += 1
            else:
                missing.append(name)
        if opened:
            return
        if missing:
            self._open_folders(missing, quiet=True)
            if quiet:
                self.status.configure(text="Keine HTML — Ordner geöffnet.")
                return
            messagebox.showinfo("Media Overview", "Keine HTML-Datei — der Ordner wurde stattdessen geöffnet.")
            return
        if quiet:
            self.status.configure(text="Für diese Zeile gibt es noch keine HTML-Datei.")
        else:
            messagebox.showinfo("Media Overview", "Für die Auswahl gibt es noch keine HTML-Datei.")

    def _open_folders(self, names: list[str], *, quiet: bool) -> None:
        target = self._target(silent=quiet)
        if target is None or not names:
            if not quiet:
                messagebox.showinfo("Media Overview", "Nichts ausgewählt.")
            return
        opened = 0
        for name in names[:8]:
            path = target / name
            if path.is_dir():
                open_path(path)
                opened += 1
        if opened:
            return
        if not quiet:
            messagebox.showinfo("Media Overview", "Ordner nicht gefunden.")

    def start(self) -> None:
        if self._busy:
            return
        target = self._target()
        if target is None:
            return
        try:
            seconds = float(self.thumb_sec.get().strip() or "5")
        except ValueError:
            messagebox.showerror("Media Overview", "Video-Sekunde muss eine Zahl sein.")
            return
        if not self.names:
            self.preview()
        chosen = self._selected_names()
        if not chosen:
            messagebox.showinfo("Media Overview", "Keine Unterordner angehakt.")
            return
        self._busy = True
        self._run_btn.configure(state="disabled", text="Bitte warten…")
        self.status.configure(text=f"Erzeuge {len(chosen)} Übersicht(en)…")
        self._persist()
        threading.Thread(
            target=self._run,
            args=(target, self.keep_images.get(), max(0.0, seconds), chosen),
            daemon=True,
        ).start()

    def _run(self, target: Path, keep_images: bool, thumb_sec: float, only: list[str]) -> None:
        try:
            log_file = target / "MedienUebersicht.log"
            init_logging(log_file)
            started = time.time()
            files = process_root(target, keep_images=keep_images, thumb_sec=thumb_sec, only=only)
            elapsed = time.time() - started
            self.root.after(0, lambda: self._done(files, elapsed, log_file))
        except Exception as error:
            self.root.after(0, lambda: self._fail(error))

    def _done(self, files: list[Path], elapsed: float, log_file: Path) -> None:
        self._busy = False
        self._created = files
        try:
            self._run_btn.configure(state="normal", text="Übersicht erstellen")
        except tk.TclError:
            return
        if not files:
            self.status.configure(text="Keine HTML-Dateien erzeugt.")
            messagebox.showinfo("Media Overview", "Keine HTML-Dateien erzeugt.")
            return
        self.preview()
        self.status.configure(text=f"Fertig: {len(files)} HTML in {elapsed:.1f}s · {log_file.name}")
        if self.open_when_done.get():
            open_path(files[0])
        messagebox.showinfo(
            "Media Overview",
            f"{len(files)} HTML-Datei(en) erzeugt.\nDoppelklick oder „HTML öffnen“ zeigt sie im Browser.",
        )

    def _fail(self, error: Exception) -> None:
        self._busy = False
        try:
            self._run_btn.configure(state="normal", text="Übersicht erstellen")
        except tk.TclError:
            return
        self.status.configure(text=f"Fehler: {error}")
        messagebox.showerror("Media Overview", str(error))


def run_gui(folder: str = "") -> int:
    if tk is None or ttk is None:
        print("Tkinter is required for the window.", file=sys.stderr)
        return 2
    _add_common()
    try:
        from common.launch import enable_dpi_awareness

        enable_dpi_awareness()
    except ImportError:
        if sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    win = tk.Tk()
    MediaOverviewApp(win, folder=folder)
    win.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reciplate companion: HTML gallery of recipe PDFs/DOCX/videos per subfolder."
    )
    parser.add_argument("root", nargs="?", help="Recipe library or section (omit this to pick it in the window)")
    args = parser.parse_args()
    return run_gui(args.root or "")


if __name__ == "__main__":
    raise SystemExit(main())
