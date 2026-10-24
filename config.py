from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return Path(meipass)
    return app_dir()


def default_config_path() -> Path:
    return app_dir() / "config.json"


def example_config_path() -> Path:
    beside = app_dir() / "config.example.json"
    if beside.is_file():
        return beside
    return resource_dir() / "config.example.json"


@dataclass(frozen=True)
class Settings:
    recipes_root: Path
    template_tex: Path
    sticker: Path
    sections: dict[str, Path]
    default_section: str
    cookies_from_browser: str
    folder_code: int
    config_path: Path

    def section_path(self, name: str) -> Path:
        return self.sections[name]


class ConfigError(RuntimeError):
    pass


def _config_env() -> str:
    return os.environ.get("RECIPLATE_CONFIG", "").strip() or os.environ.get(
        "RECIPE_INBOX_CONFIG", ""
    ).strip()


def config_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    env = _config_env()
    if env:
        return Path(env).expanduser()
    return default_config_path()


def _as_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (root / path).resolve()


def _seed_config_from_example() -> None:
    dest = default_config_path()
    if dest.is_file():
        return
    example = example_config_path()
    if not example.is_file():
        return
    shutil.copy2(example, dest)
    raise ConfigError(
        f"Created {dest} from the example.\n"
        "Set recipes_root (and folders if needed), then start again."
    )


def load_settings(path: Path | None = None) -> Settings:
    if path is None and not _config_env():
        _seed_config_from_example()
    file = config_path(path)
    if not file.is_file():
        raise ConfigError(
            f"No personal config at {file}.\n"
            f"Copy {example_config_path().name} to {default_config_path().name} and set recipes_root."
        )
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigError(f"Invalid JSON in {file}: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError(f"{file} must contain a JSON object.")
    try:
        root_raw = str(data["recipes_root"]).strip()
    except KeyError as error:
        raise ConfigError(f"{file} is missing {error.args[0]!r}.") from error
    if not root_raw:
        raise ConfigError(f"{file} has an empty recipes_root.")
    root = Path(root_raw).expanduser()
    sections_raw = data.get("sections") or {}
    if not isinstance(sections_raw, dict) or not sections_raw:
        raise ConfigError("config.sections must be a non-empty object of name → folder.")
    sections = {str(name): _as_path(root, str(rel)) for name, rel in sections_raw.items()}
    default_section = str(data.get("default_section") or next(iter(sections)))
    if default_section not in sections:
        raise ConfigError(f"default_section {default_section!r} is not in sections.")
    try:
        folder_code = int(data.get("folder_code") or 3)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{file} has an invalid folder_code.") from error
    return Settings(
        recipes_root=root,
        template_tex=_as_path(root, str(data.get("template_tex") or "ignore/LaTeX/recipe.tex")),
        sticker=_as_path(root, str(data.get("sticker") or "ignore/LaTeX/img/sticker-homemade.png")),
        sections=sections,
        default_section=default_section,
        cookies_from_browser=str(data.get("cookies_from_browser") or "").strip(),
        folder_code=folder_code,
        config_path=file,
    )
