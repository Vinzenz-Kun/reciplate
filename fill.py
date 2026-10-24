from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from copy_template import apply_shared_graphicspath
from language import DE, video_note as default_video_note


@dataclass
class IngredientGroup:
    heading: str
    items: list[str]


@dataclass
class RecipeDraft:
    title: str
    handle: str
    url: str
    image_name: str
    groups: list[IngredientGroup] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)
    notes: str = ""
    language: str = DE
    video_language: str = DE
    video_note: str = ""


LATEX_SPECIALS = (
    ("\\", r"\textbackslash{}"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("$", r"\$"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
)


def latex_text(value: str) -> str:
    out = value.strip()
    for raw, escaped in LATEX_SPECIALS:
        out = out.replace(raw, escaped)
    return out


def latex_url(value: str) -> str:
    """Escape characters that would break \\newcommand{\\RecipeURL}{...}."""
    return (
        value.strip()
        .replace("\\", "/")
        .replace("%", r"\%")
        .replace("#", r"\#")
        .replace("{", "")
        .replace("}", "")
    )


def itemize(items: list[str], language: str = DE) -> str:
    todo = "TODO: Zutaten ergänzen" if language == DE else "TODO: add ingredients"
    lines = ["      \\begin{itemize}[itemsep=0pt, topsep=2pt, parsep=0pt]"]
    if not items:
        lines.append(f"        \\item \\textit{{{todo}}}")
    else:
        for item in items:
            lines.append(f"        \\item {latex_text(item)}")
    lines.append("      \\end{itemize}")
    return "\n".join(lines)


def ingredients_body(groups: list[IngredientGroup], language: str = DE) -> str:
    usable = [group for group in groups if group.items]
    if not usable:
        return itemize([], language)
    chunks: list[str] = []
    for group in usable:
        if group.heading:
            chunks.append(f"      {latex_text(group.heading)}")
        chunks.append(itemize(group.items, language))
    return "\n".join(chunks)


def steps_body(steps: list[str], tips: list[str], language: str = DE) -> str:
    todo = "TODO: Zubereitung ergänzen" if language == DE else "TODO: add directions"
    tip_heading = "Tipps" if language == DE else "Tips"
    lines = ["  \\begin{enumerate}"]
    if not steps:
        lines.append(f"    \\item \\textit{{{todo}}}")
    else:
        for step in steps:
            lines.append(f"    \\item {latex_text(step)}")
    lines.append("  \\end{enumerate}")
    if tips:
        lines.append(f"  {tip_heading}")
        lines.append("  \\begin{itemize}")
        for tip in tips:
            lines.append(f"    \\item {latex_text(tip)}")
        lines.append("  \\end{itemize}")
    return "\n".join(lines)


def apply_sheet_language(text: str, language: str) -> str:
    if language == DE:
        text = re.sub(
            r"\\documentclass\[12pt,[^\]]*\]",
            r"\\documentclass[12pt,ngerman]",
            text,
            count=1,
        )
        text = text.replace("title=Ingredients", "title=Zutaten")
        text = text.replace("title=Directions", "title=Zubereitung")
        return text
    text = re.sub(
        r"\\documentclass\[12pt,[^\]]*\]",
        r"\\documentclass[12pt,english]",
        text,
        count=1,
    )
    text = text.replace("title=Zutaten", "title=Ingredients")
    text = text.replace("title=Zubereitung", "title=Directions")
    return text


def fill_copy(tex_path: Path, draft: RecipeDraft, *, master: Path | None = None) -> None:
    """Rewrite only the destination .tex copy. Never call this on the master template."""
    resolved = tex_path.resolve()
    if master is not None and resolved == master.resolve():
        raise RuntimeError("Refusing to fill the master template.")
    if "ignore" in resolved.parts and resolved.name == "recipe.tex" and resolved.parent.name == "LaTeX":
        raise RuntimeError("Refusing to fill ignore/LaTeX/recipe.tex.")
    text = tex_path.read_text(encoding="utf-8")
    text = re.sub(
        r"\\newcommand\{\\RecipeTitle\}\{[^}]*\}",
        lambda _match: "\\newcommand{\\RecipeTitle}{" + latex_text(draft.title) + "}",
        text,
        count=1,
    )
    handle = latex_text(draft.handle) if draft.handle.strip() else ""
    text = re.sub(
        r"\\newcommand\{\\RecipeHandle\}\{[^}]*\}",
        lambda _match: "\\newcommand{\\RecipeHandle}{" + handle + "}",
        text,
        count=1,
    )
    url = latex_url(draft.url)
    note = draft.video_note.strip() or default_video_note(draft.language, draft.video_language)
    note_cmd = "\\newcommand{\\RecipeVideoNote}{" + latex_text(note) + "}"
    if re.search(r"\\newcommand\{\\RecipeVideoNote\}", text):
        text = re.sub(
            r"\\newcommand\{\\RecipeVideoNote\}\{[^}]*\}",
            lambda _match: note_cmd,
            text,
            count=1,
        )
        text = re.sub(
            r"\\newcommand\{\\RecipeURL\}\{[^}]*\}",
            lambda _match: "\\newcommand{\\RecipeURL}{" + url + "}",
            text,
            count=1,
        )
    else:
        text = re.sub(
            r"\\newcommand\{\\RecipeURL\}\{[^}]*\}",
            lambda _match: "\\newcommand{\\RecipeURL}{" + url + "}\n" + note_cmd,
            text,
            count=1,
        )
    if r"{\footnotesize \RecipeVideoNote}" not in text:
        text = re.sub(
            r"(\\url\{\\RecipeURL\}\\fi)",
            lambda match: match.group(1) + "\\par\n    {\\footnotesize \\RecipeVideoNote}",
            text,
            count=1,
        )
    text = apply_sheet_language(text, draft.language)
    text = apply_shared_graphicspath(text, master) if master is not None else text
    image = draft.image_name.replace("\\", "/")
    text = re.sub(
        r"(\\img\[width=\\ImageFixedWidth,keepaspectratio\]\{)[^}]+(\})",
        lambda match: match.group(1) + image + match.group(2),
        text,
        count=1,
    )
    body = ingredients_body(draft.groups, draft.language)
    text = re.sub(
        r"(\\begin\{ingredients\}\s*).*?(\\end\{ingredients\})",
        lambda match: match.group(1) + "\n" + body + "\n    " + match.group(2),
        text,
        count=1,
        flags=re.S,
    )
    directions = steps_body(draft.steps, draft.tips, draft.language)
    text = re.sub(
        r"(\\begin\{directionswide\}\s*).*?(\\end\{directionswide\})",
        lambda match: match.group(1) + "\n" + directions + "\n" + match.group(2),
        text,
        count=1,
        flags=re.S,
    )
    tex_path.write_text(text, encoding="utf-8")
