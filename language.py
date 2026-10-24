from __future__ import annotations

import re

DE = "de"
EN = "en"
LANGS = (DE, EN)

_TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß]+")

_DE = frozenset(
    """
    und oder mit für den die das ein eine eines zum zur nach nicht auch auf aus
    zutaten zubereitung marinade soße sosse sauce tipps anleitung
    mehl zucker salz pfeffer öl olivenöl zwiebel knoblauch butter sahne milch
    braten mischen rühren schneiden erhitzen kochen backen geben lassen
    el tl messerspitze minuten minute gram milliliter
    """.split()
)
_EN = frozenset(
    """
    and or with for the a an into onto until then also not
    ingredients directions method marinade sauce tips steps
    flour sugar salt pepper oil onion garlic butter cream milk
    fry mix stir cut heat cook bake add let simmer
    tbsp tsp teaspoon tablespoon minutes minute cup cups
    """.split()
)


def detect_language(*parts: str) -> str:
    text = " ".join(parts)
    de_hits = 0
    en_hits = 0
    for raw in _TOKEN.findall(text.lower()):
        if raw in _DE:
            de_hits += 2
        if raw in _EN:
            en_hits += 2
        if any(ch in raw for ch in "äöüß"):
            de_hits += 3
    if de_hits == en_hits:
        return DE if re.search(r"[ÄÖÜäöüß]", text) else EN
    return DE if de_hits > en_hits else EN


def language_name(code: str, *, in_language: str) -> str:
    names = {
        (DE, DE): "Deutsch",
        (DE, EN): "German",
        (EN, DE): "Englisch",
        (EN, EN): "English",
    }
    return names.get((code, in_language), code)


def video_note(sheet: str, video: str) -> str:
    spoken = language_name(video, in_language=sheet)
    if sheet == video:
        suffix = " (Original)" if sheet == DE else " (original)"
        return f"Video: {spoken}{suffix}"
    if sheet == DE:
        return f"Video: {spoken} (Originalsprache des Videos)"
    return f"Video: {spoken} (language of the video)"


def other_language(code: str) -> str:
    return EN if code == DE else DE
