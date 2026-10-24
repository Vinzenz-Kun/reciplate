from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from copy_template import tidy_recipe_folder
from language import LANGS


class CompileError(RuntimeError):
    pass


_SEARCH = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/MiKTeX/miktex/bin/x64/lualatex.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "MiKTeX/miktex/bin/x64/lualatex.exe",
    Path(r"C:\Program Files\MiKTeX\miktex\bin\x64\lualatex.exe"),
    Path(r"C:\Program Files (x86)\MiKTeX\miktex\bin\lualatex.exe"),
)


@lru_cache(maxsize=1)
def find_lualatex() -> Path | None:
    for name in ("lualatex", "lualatex.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    for path in _SEARCH:
        if path.is_file():
            return path
    texlive = Path(r"C:\texlive")
    if texlive.is_dir():
        matches = sorted(texlive.glob("*/bin/windows/lualatex.exe"), reverse=True)
        if matches:
            return matches[0]
    return None


def _run_hidden(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    kwargs: dict = {
        "cwd": str(cwd),
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": 180,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(command, **kwargs)


def _log_tail(folder: Path, job: str, limit: int = 40) -> str:
    log = folder / f"{job}.log"
    if not log.is_file():
        return ""
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-limit:])


def compile_tex(tex_path: Path, *, passes: int = 2) -> Path:
    """Compile one .tex copy with LuaLaTeX and return the final PDF path."""
    engine = find_lualatex()
    if engine is None:
        raise CompileError(
            "LuaLaTeX was not found. Install TeX Live or MiKTeX and keep lualatex on PATH."
        )
    folder = tex_path.parent
    lang = tex_path.suffixes[-2][1:] if len(tex_path.suffixes) >= 2 else "tex"
    if lang not in LANGS:
        lang = tex_path.stem.split(".")[-1] if "." in tex_path.stem else "out"
    job = f"__build_{lang}"
    pdf_tmp = folder / f"{job}.pdf"
    pdf_final = tex_path.with_suffix(".pdf")
    source = tex_path.name.replace("\\", "/")
    job_arg = r"\input{\detokenize{" + source + "}}"
    command = [
        str(engine),
        "-interaction=nonstopmode",
        "-file-line-error",
        "-synctex=0",
        f"-jobname={job}",
        job_arg,
    ]
    last: subprocess.CompletedProcess[str] | None = None
    try:
        for _ in range(passes):
            last = _run_hidden(command, cwd=folder)
            if not pdf_tmp.is_file():
                detail = (last.stderr or last.stdout or "").strip() or _log_tail(folder, job)
                raise CompileError(f"LuaLaTeX produced no PDF for {tex_path.name}.\n{detail[-2000:]}")
    except subprocess.TimeoutExpired as error:
        raise CompileError(f"LuaLaTeX timed out on {tex_path.name}.") from error
    if pdf_final.exists() and pdf_final.resolve() != pdf_tmp.resolve():
        pdf_final.unlink()
    pdf_tmp.replace(pdf_final)
    return pdf_final


def compile_folder(folder: Path, copies: dict[str, Path]) -> tuple[list[Path], str]:
    """Compile DE/EN copies. Returns PDF paths and a warning string (empty if all ok)."""
    pdfs: list[Path] = []
    problems: list[str] = []
    if find_lualatex() is None:
        tidy_recipe_folder(folder)
        return [], (
            "LuaLaTeX was not found. Install TeX Live or MiKTeX and keep lualatex on PATH."
        )
    try:
        for lang in LANGS:
            tex = copies.get(lang) or folder / f"{folder.name}.{lang}.tex"
            if not tex.is_file():
                continue
            try:
                pdfs.append(compile_tex(tex))
            except CompileError as error:
                problems.append(str(error))
    finally:
        tidy_recipe_folder(folder)
    return pdfs, "\n".join(problems)
