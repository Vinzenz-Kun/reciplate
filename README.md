# Reciplate

[English](README.md) | [Deutsch](README.de.md) | [日本語](README.ja.md)

Turn an Instagram reel (or a local PDF) into a bilingual LuaLaTeX recipe: German and English sheets, video, cover photo, compiled PDFs.

The master template is never written. The program copies it, fills the copies, then compiles. Python 3.10+. Works on its own; if the toolbox `common/` folder sits next to this one, Reciplate uses that shared UI.

Start `reciplate.py`. Helpers live in `lib/`, tests in `tests/`.

## Setup

```text
copy config.example.json local\config.json
```

Set `recipes_root` to your recipes library (`~/Recipes` in the example is expanded). Paths in `template_tex` / `sections` can be relative to that root. Optional: `RECIPLATE_CONFIG` pointing at another JSON file.

```text
pip install -r requirements.txt
python reciplate.py
```

`local/config.json` is gitignored. Commit only `config.example.json` (placeholders, no personal paths). Local PDFs need `pypdf` (already in `requirements.txt`).

## What you get per recipe

Inside `[3][nn]slug/`:

- `{folder}.de.tex` / `{folder}.en.tex`
- `{folder}.de.pdf` / `{folder}.en.pdf` (LuaLaTeX, if installed)
- video (`{folder}.mp4`, …)
- `{folder}.jpg` (Instagram thumbnail or a frame from the video)

Auxiliary files (`.aux`, `.log`, stickers, `source.json`, `img/`) are removed. The sticker comes from the shared template `img/` folder via `\graphicspath`.

## Workflow

1. Paste an Instagram URL, or click **PDF…** for a local file (Firefox/Chrome/Edge cookies if Instagram blocks the download).
2. Fetch metadata — caption or PDF text is split into ingredients and steps; edit in the window.
3. Create folder — copy template, translate the other language, download media, compile PDFs.
4. Same URL again → warning, Cancel or Update. Update keeps the number (`[3][36]`), renames folder/files to the current title, and can move the recipe between sections (Kochen/Backen). New numbers are the next `[3][n]` across all sections, not only the selected one.

Fetch, download, translate, and compile run in the background so the window stays usable. Instagram links are stored without tracking query strings (`?igsh=…`).

Language is detected from the text and printed on both sheets (`Video: Deutsch (Original)`, …).

Translation uses MyMemory, then Google Translate (`deep-translator` if installed, otherwise the public HTTP APIs). Ingredients in the window can be plain lines — dashes are optional; `Für die Panade` starts a group.

## EXE (Windows)

```text
.\Build.ps1
```

Puts `Reciplate.exe` next to `config.json`. `yt-dlp` is bundled. Close the running EXE before rebuilding, or use `dist\Reciplate.exe`.

LuaLaTeX still has to be installed on the machine (TeX Live or MiKTeX).

## Tests

```text
python -m unittest discover -s tests -t .
```

## GitHub

This folder is already its own repository. `local/`, `*.last`, `build/`, `dist/`, and `Reciplate.exe` stay local. Do not push the parent `functional_programs` tree.
