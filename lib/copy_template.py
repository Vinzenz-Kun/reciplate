from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from language import LANGS

STICKER = "sticker-homemade.png"
KEEP_SUFFIXES = {".tex", ".pdf", ".mp4", ".mkv", ".webm", ".mov"}
JUNK_NAMES = {"source.json", "cover.jpg", STICKER}
JUNK_SUFFIXES = {
    ".json",
    ".webp",
    ".part",
    ".ytdl",
    ".tmp",
    ".aux",
    ".log",
    ".out",
    ".toc",
    ".fls",
    ".fdb_latexmk",
    ".bcf",
    ".blg",
    ".bbl",
    ".nav",
    ".snm",
    ".vrb",
    ".idx",
    ".ilg",
    ".ind",
    ".lof",
    ".lot",
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def shared_img_dir(template_tex: Path) -> Path:
    return (template_tex.parent / "img").resolve()


def latex_graphicspath(img_dir: Path) -> str:
    return img_dir.as_posix().rstrip("/") + "/"


def apply_shared_graphicspath(text: str, template_tex: Path) -> str:
    img = shared_img_dir(template_tex)
    if not img.is_dir() or r"\graphicspath" not in text:
        return text
    path = latex_graphicspath(img)
    return re.sub(
        r"\\graphicspath\{[^}]*\}",
        r"\\graphicspath{ {" + path + "} }",
        text,
        count=1,
    )


def tidy_recipe_folder(folder: Path) -> None:
    """Keep only .tex, PDFs, video, and the recipe cover jpg."""
    if not folder.is_dir():
        return
    for path in list(folder.iterdir()):
        if path.is_dir():
            if path.name.lower() == "img":
                shutil.rmtree(path, ignore_errors=True)
            continue
        suffix = path.suffix.lower()
        name = path.name.lower()
        if name.startswith("__build_"):
            path.unlink(missing_ok=True)
            continue
        if suffix in KEEP_SUFFIXES:
            continue
        if path.stem == folder.name and suffix in {".jpg", ".jpeg"}:
            continue
        if (
            name in JUNK_NAMES
            or suffix in JUNK_SUFFIXES
            or name.startswith("source.")
            or name.endswith(".synctex.gz")
            or name.endswith(".run.xml")
        ):
            path.unlink(missing_ok=True)


def copy_template(template_tex: Path, destination: Path, *, overwrite: bool = False) -> dict[str, Path]:
    """Copy the master recipe.tex into DE and EN files. The master is read-only here."""
    if not template_tex.is_file():
        raise FileNotFoundError(f"Template not found: {template_tex}")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Folder already exists: {destination}")
    if destination.exists() and not destination.is_dir():
        raise FileExistsError(f"Destination is not a folder: {destination}")
    before = file_hash(template_tex)
    destination.mkdir(exist_ok=True)
    text = apply_shared_graphicspath(
        template_tex.read_text(encoding="utf-8"),
        template_tex,
    )
    copies: dict[str, Path] = {}
    for lang in LANGS:
        dest_tex = destination / f"{destination.name}.{lang}.tex"
        if dest_tex.resolve() == template_tex.resolve():
            raise RuntimeError("Refusing to fill the master template in place.")
        dest_tex.write_text(text, encoding="utf-8")
        copies[lang] = dest_tex
    after = file_hash(template_tex)
    if before != after:
        raise RuntimeError("Master template changed while copying — aborting.")
    tidy_recipe_folder(destination)
    return copies
