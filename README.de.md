# Reciplate

[English](README.md) | **Deutsch** | [日本語](README.ja.md)

Aus einem Instagram-Reel (oder einem lokalen PDF) wird ein zweisprachiges LuaLaTeX-Rezept: deutsche und englische Blätter, Video, Coverfoto, kompilierte PDFs.

Die Master-Vorlage wird nie überschrieben. Das Programm kopiert sie, füllt nur die Kopien und kompiliert danach. Python 3.10+. Läuft allein; liegt `common/` daneben, kommt die gemeinsame Oberfläche.

Start: `reciplate.py` legt Rezeptordner an. `media_overview.py` baut HTML-Galerien davon (Abschnitte wie Kochen/Backen, oder ein einzelner Abschnitt). Hilfscode in `lib/`, Tests in `tests/`.

## Einrichtung

```text
copy config.example.json local\config.json
```

`recipes_root` auf deine Rezepte-Bibliothek setzen (`~/Recipes` im Beispiel wird expandiert). Pfade in `template_tex` / `sections` dürfen relativ zu diesem Root sein. Optional: Umgebungsvariable `RECIPLATE_CONFIG` auf eine andere JSON-Datei.

```text
pip install -r requirements.txt
python reciplate.py
```

`local/config.json` ist gitignore. Committe nur `config.example.json` — dort stehen Platzhalter, keine persönlichen Pfade. Lokale PDFs brauchen `pypdf` (steht in `requirements.txt`).

## Was pro Rezept übrig bleibt

In `[3][nn]slug/`:

- `{folder}.de.tex` / `{folder}.en.tex`
- `{folder}.de.pdf` / `{folder}.en.pdf` (LuaLaTeX, falls installiert)
- Video (`{folder}.mp4`, …)
- `{folder}.jpg` (Instagram-Thumbnail oder ein Frame aus dem Video)

Hilfsdateien (`.aux`, `.log`, Sticker, `source.json`, `img/`) werden entfernt. Der Sticker kommt über `\graphicspath` aus dem gemeinsamen Vorlagen-`img/`.

## Ablauf

1. Instagram-URL einfügen oder **PDF…** für eine lokale Datei (Firefox/Chrome/Edge-Cookies, falls Instagram den Download blockt). Nacktes `www.instagram.com/...` wird zu `https://…`.
2. Metadaten holen — Caption oder PDF-Text wird in Zutaten und Schritte geteilt; im Fenster nachbearbeiten. Zutatenzeilen brauchen kein `-`.
3. Ordner anlegen — Vorlage kopieren, andere Sprache übersetzen, Medien laden, PDFs kompilieren.
4. Dieselbe URL nochmal → Warnung, Abbrechen oder Update. Update behält die Nummer (`[3][36]`), benennt Ordner/Dateien um und kann zwischen Abschnitten (z. B. Kochen/Backen) verschieben. Neue Nummern sind das nächste `[3][n]` über alle Abschnitte.

Fetch, Download, Übersetzung und Compile laufen im Hintergrund. Tracking-Parameter (`?igsh=…`) fallen aus der gespeicherten URL.

Die Sprache wird aus dem Text erkannt und auf beiden Blättern vermerkt (`Video: Deutsch (Original)`, …).

Übersetzung: MyMemory, dann Google Translate (`deep-translator` oder öffentliche HTTP-APIs).

## Media Overview

Begleitfenster für dieselbe Rezepte-Bibliothek. `recipes_root` wählen (oder einen Abschnitt). Angehakte Unterordner werden zu `Name.html`: Suche, Video auf der Karte, Klick zeigt das ganze PDF-Rezept.

```text
python media_overview.py
python media_overview.py "D:\Rezepte"
```

Optionale Vorschaubilder: `PyMuPDF`, `opencv-python`. Das Fenster öffnet sich auch ohne. Word oder LibreOffice kann neben einer reinen DOCX eine PDF drucken. `ignore/` fällt raus; Thumbs liegen in `images/`.

## EXE (Windows)

```text
.\Build.ps1
```

Legt `Reciplate.exe` neben `config.json`. `yt-dlp` ist eingebunden. Laufende EXE vor dem Neu-Build schließen.

LuaLaTeX muss auf dem Rechner installiert sein (TeX Live oder MiKTeX).

## Tests

```text
python -m unittest discover -s tests -t .
```

## GitHub

Dieser Ordner ist schon ein eigenes Repository. `local/`, `*.last`, `build/`, `dist/` und `Reciplate.exe` bleiben lokal. Die Eltern-Toolbox `functional_programs` nicht mitpushen.
