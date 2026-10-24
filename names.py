from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path


_WIN_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_TITLE_PREFIX = re.compile(r"^\[\d+\]\[\d+\]\s*")


def recipe_title_stem(title: str) -> str:
    """Drop a leading [code][n] so folder names are not doubled."""
    text = _TITLE_PREFIX.sub("", (title or "").strip()).strip()
    return text or "recipe"


def slug(title: str) -> str:
    table = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})
    text = recipe_title_stem(title).translate(table)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _WIN_BAD.sub("-", text)
    text = re.sub(r"[^\w]+", "-", text, flags=re.UNICODE)
    text = text.strip("-").lower()
    return text[:60] or "recipe"


def folder_prefix(code: int) -> re.Pattern[str]:
    return re.compile(rf"^\[{code}\]\[(\d+)\]")


def folder_number(name: str, code: int = 3) -> int | None:
    match = folder_prefix(code).match(name) or re.match(r"^\[\d+\]\[(\d+)\]", name)
    return int(match.group(1)) if match else None


def next_insta_number(parent: Path | Iterable[Path], code: int = 3) -> int:
    """Next [code][n] across one folder or all section folders."""
    roots = [parent] if isinstance(parent, Path) else list(parent)
    highest = 0
    pattern = folder_prefix(code)
    for root in roots:
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            match = pattern.match(child.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def folder_name(number: int, title: str, code: int = 3) -> str:
    return f"[{code}][{number:02d}]{slug(title)}"


def rename_stem_files(folder: Path, old_stem: str, new_stem: str) -> None:
    """Rename files whose name starts with the old folder stem."""
    if old_stem == new_stem or not folder.is_dir():
        return
    for path in sorted(folder.iterdir(), key=lambda item: len(item.name), reverse=True):
        if not path.is_file() or not path.name.startswith(old_stem):
            continue
        suffix = path.name[len(old_stem) :]
        if suffix and not suffix.startswith("."):
            continue
        target = folder / f"{new_stem}{suffix}"
        if target.resolve() == path.resolve():
            continue
        if target.exists():
            target.unlink()
        path.replace(target)


def move_recipe_folder(source: Path, destination: Path) -> Path:
    """Rename or move a recipe folder. Same volume; overwrites are refused."""
    if source.resolve() == destination.resolve():
        return source
    if destination.exists():
        raise FileExistsError(f"Folder already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)
    return destination


_INSTA_ID = re.compile(
    r"(?:instagram\.com|instagr\.am)/(reels?|p|tv)/([^/?#]+)",
    re.I,
)
_RECIPE_URL = re.compile(r"\\newcommand\{\\RecipeURL\}\{([^}]*)\}")


def recipe_url_key(url: str) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    match = _INSTA_ID.search(text)
    if match:
        return match.group(2).rstrip("/").lower()
    stripped = re.sub(r"[?#].*$", "", text).rstrip("/").lower()
    stripped = re.sub(r"^https?://(www\.)?", "", stripped)
    return stripped


def canonical_recipe_url(url: str) -> str:
    """Keep reel/p/tv + id; drop tracking query strings."""
    text = (url or "").strip().strip('"')
    if not text:
        return ""
    if re.match(r"(?i)(www\.)?(instagram\.com|instagr\.am)/", text) and not text.lower().startswith("http"):
        text = "https://" + text.lstrip("/")
    match = _INSTA_ID.search(text)
    if not match:
        return text
    kind = match.group(1).lower()
    if kind == "reels":
        kind = "reel"
    ident = match.group(2).rstrip("/")
    return f"https://www.instagram.com/{kind}/{ident}/"


def url_from_recipe_folder(folder: Path) -> str:
    source = folder / "source.json"
    if source.is_file():
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            for field in ("url", "instagram_url", "source_url"):
                value = str(data.get(field) or "").strip()
                if value:
                    return value
    for tex in sorted(folder.glob("*.tex")):
        try:
            text = tex.read_text(encoding="utf-8")
        except OSError:
            continue
        match = _RECIPE_URL.search(text)
        if match and match.group(1).strip():
            return match.group(1).strip().replace(r"\#", "#").replace(r"\%", "%")
    return ""


def find_folder_by_url(roots: Iterable[Path], url: str) -> Path | None:
    key = recipe_url_key(url)
    if not key:
        return None
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            found = url_from_recipe_folder(child)
            if found and recipe_url_key(found) == key:
                return child
    return None
