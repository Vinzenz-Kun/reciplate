from __future__ import annotations

import re

from fill import IngredientGroup, RecipeDraft

_SKIP = re.compile(
    r"^(?:#\w+\s*)+$|https?://|^(?:follow|link in bio|save (?:this|it)|"
    r"rezept speichern|mehr auf|werbung|anzeige|sponsored)\b",
    re.I,
)
_GENERIC_TITLE = re.compile(r"^(?:instagram|video by|reel by|image by|photo by)\b", re.I)
_BULLET = re.compile(r"^[\-\u2013\u2014•●‣▪️*\u2022]\s*")
_NUMBER = re.compile(r"^\s*(?:\d+[\.)]|[\(\[]\d+[\)\]])\s+")
_UNITS = (
    r"g|kg|mg|ml|cl|dl|l|el|tl|msp\.?|tsp|tbsp|tbs|cups?|oz|lb|"
    r"gramm|grams?|kilogramm|liter|milliliter|"
    r"prise[n]?|stück|st\.?|zehe[n]?|bund|pck\.?|packung(?:en)?|"
    r"dose[n]?|scheibe[n]?|handvoll|becher"
)
_AMOUNT = re.compile(
    rf"^(?:ca\.?\s*|approx\.?\s*|about\s*)?"
    rf"(?:\d+[.,]?\d*|\d+\s*/\s*\d+|[½¼¾⅓⅔⅛]|ein[es]?|a|an|one|two|three)\s*"
    rf"(?:{_UNITS})?\b",
    re.I,
)
_AMOUNT_WITH_UNIT = re.compile(
    rf"^(?:ca\.?\s*|approx\.?\s*|about\s*)?"
    rf"(?:\d+[.,]?\d*|\d+\s*/\s*\d+|[½¼¾⅓⅔⅛])\s*"
    rf"(?:{_UNITS})\b",
    re.I,
)
_UNIT_AT_START = _AMOUNT_WITH_UNIT
_ING_HEAD = re.compile(
    r"^(?:zutaten|ingredients|du brauchst|you(?:'ll| will) need|shopping list|"
    r"für \d+|serves?|portionen|zutatenliste)\b",
    re.I,
)
_STEP_HEAD = re.compile(
    r"^(?:zubereitung|anleitung|so geht'?s|methode|method|directions?|"
    r"instructions?|steps?|zubereiten|how to|zum zubereiten)\b",
    re.I,
)
_TIP_HEAD = re.compile(r"^(?:tipps?|hinweise?|notes?|tips?)\b", re.I)
_GROUP_HEAD = re.compile(
    r"^(?:für (?:die |den |das )?|zum |fürs )?"
    r"(?:marinade|sauce|soße|sosse|dressing|teig|boden|belag|topping|"
    r"panade|servieren|serving|dip|filling|fülle|glasur|frosting|streusel)\b",
    re.I,
)
_FOR_HEAD = re.compile(
    r"^(?:für (?:die |den |das |s )?|for (?:the )?|zum |zur |fürs )\S",
    re.I,
)
_SERVINGS = re.compile(
    r"^\(?\s*\d+\s*(?:-\s*\d+\s*)?(?:portionen?|servings?|personen?|personen|p\.?|pers\.?)\s*\)?\s*$",
    re.I,
)
_COOK_VERBS = frozenset(
    """
    schneiden hacken mischen rühren erhitzen braten anbraten backen kochen
    geben lassen pressen marinieren würzen ablöschen aufkochen vorheizen
    schälen waschen vermengen hinzufügen unterheben pürieren servieren toppen
    dünsten schmelzen auflösen einpinseln ziehen ausdrücken würfeln reiben
    bröseln röstest rösten dämpfen füllen streichen kneten gehen verrühren
    einschneiden anrichten abtropfen erhitze brate mische rühre schneide
    dazugeben hinzugeben untermischen einrühren unterheben zugeben
    mix cut heat bake cook add fry stir pour whisk simmer boil chop mince
    drain press marinate season preheat serve top combine blend roast toast
    fold spread slice dice grate crush toss sauté saute brown reduce
    knead rest proof
    """.split()
)
_TASTE = re.compile(
    r"^(?:optional|nach geschmack|to taste|etwas|a pinch|salz|pfeffer|öl|oil|salt|pepper)\b",
    re.I,
)
_TIME_TEMP = re.compile(
    r"\b(?:\d+\s*(?:-\s*)?\d*\s*min(?:uten)?|°c|grad|until|solange|anschließend|danach)\b",
    re.I,
)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÄÖÜäöüß']+", text.lower())


def _clean_line(raw: str) -> str:
    line = raw.strip()
    line = _BULLET.sub("", line)
    return re.sub(r"\s+", " ", line).strip()


def _is_skip(line: str) -> bool:
    if not line:
        return False
    letters = re.sub(r"[^A-Za-zÄÖÜäöüß]", "", line)
    if len(letters) < 3:
        return True
    return bool(_SKIP.match(line))


def _body(text: str) -> str:
    return _NUMBER.sub("", text).strip() or text.strip()


def _has_cook_verb(text: str) -> bool:
    return bool(set(_tokens(text)) & _COOK_VERBS)


def is_instruction_prose(text: str) -> bool:
    """A cooking sentence: keep it whole, even if it mentions 200g."""
    line = _body(text)
    if not line:
        return False
    if _TIME_TEMP.search(line):
        return True
    words = _tokens(line)
    verbs = set(words) & _COOK_VERBS
    if not verbs:
        return len(line) > 110
    if len(line) > 42:
        return True
    if len(words) > 6 and re.search(r"\b(?:und|and|dann|then|bis|with|mit)\b", line, re.I):
        return True
    if words and words[0] in _COOK_VERBS:
        return True
    return False


def looks_like_ingredient(text: str, *, in_list: bool = False) -> bool:
    line = _body(text)
    if not line or is_instruction_prose(line):
        return False
    if _UNIT_AT_START.match(line) or _AMOUNT_WITH_UNIT.match(line):
        return True
    if _TASTE.match(line) and len(_tokens(line)) <= 6:
        return True
    if in_list and _AMOUNT.match(line) and not _has_cook_verb(line) and len(line) <= 60:
        return True
    if in_list and 1 <= len(_tokens(line)) <= 8 and not _has_cook_verb(line) and len(line) <= 50:
        return True
    return False


def looks_like_step(text: str) -> bool:
    line = _body(text)
    if not line:
        return False
    if looks_like_ingredient(line):
        return False
    return is_instruction_prose(line) or bool(set(_tokens(line)[:5]) & _COOK_VERBS)


_NEXT_AMOUNT = re.compile(
    rf"(?:ca\.?\s*)?(?:\d+[.,]?\d*|\d+\s*/\s*\d+|[½¼¾⅓⅔⅛])\s*(?:{_UNITS})\b",
    re.I,
)


_TIME_WORD = re.compile(r"^(?:\d+[.,]?\d*\s*)?(?:min(?:uten)?|std\.?|stunden?|sek(?:unden)?|°c|grad)\b", re.I)
_FILLER = frozenset("der die das den dem des ein eine eines einen einem of a an the mit with und and oder or vom von zum zur".split())


def _is_time_span(word: str, nxt: str = "") -> bool:
    return bool(_TIME_WORD.match(word) or _TIME_WORD.match(f"{word} {nxt}".strip()))


def _name_before_instruction(after: str) -> tuple[str, str]:
    words = after.split()
    take = 0
    while take < len(words) and take < 8:
        token = _tokens(words[take])
        nxt = words[take + 1] if take + 1 < len(words) else ""
        following = _tokens(nxt) if nxt else []
        if token and token[0] in _COOK_VERBS:
            break
        if _is_time_span(words[take], nxt):
            break
        if take > 0 and following and following[0] in _COOK_VERBS:
            break
        if _NEXT_AMOUNT.match(words[take]):
            break
        take += 1
    return " ".join(words[:take]).strip(" ,;/"), " ".join(words[take:]).strip(" ,;/")


def _peel_leading_ingredients(line: str) -> tuple[list[str], str]:
    """Take g/EL/ml items from the start. Leave cooking sentences intact."""
    ingredients: list[str] = []
    rest = line.strip()
    while rest:
        match = _AMOUNT_WITH_UNIT.match(rest)
        if not match:
            break
        after = rest[match.end() :].lstrip(" ,;/")
        next_amt = _NEXT_AMOUNT.search(after)
        if next_amt and not _has_cook_verb(after[: next_amt.start()]):
            name = after[: next_amt.start()].strip(" ,;/")
            ingredients.append(f"{match.group(0)} {name}".strip())
            rest = after[next_amt.start() :].strip()
            continue
        name, leftover = _name_before_instruction(after)
        if leftover:
            first = _tokens(leftover)
            if first and first[0] in _COOK_VERBS:
                break
        if not name and leftover:
            break
        ingredients.append(f"{match.group(0)} {name}".strip())
        rest = leftover
        if leftover:
            break
    return ingredients, rest


def _split_ingredient_commas(line: str) -> list[str] | None:
    if "," not in line or is_instruction_prose(line):
        return None
    parts = [part.strip() for part in line.split(",") if part.strip()]
    if len(parts) < 2:
        return None
    if all(looks_like_ingredient(part) for part in parts):
        return parts
    return None


def _normalize_lines(caption: str) -> list[str]:
    text = caption.replace("\r", "")
    text = re.sub(r"[•●‣▪️]+", "\n", text)
    if text.count("\n") < 2 and re.search(r"\s+\d+[\.)]\s+", text):
        text = re.sub(r"\s+(\d+[\.)]\s+)", r"\n\1", text)
    lines: list[str] = []
    for raw in text.splitlines():
        line = _clean_line(raw)
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if _is_skip(line):
            continue
        numbered = bool(_NUMBER.match(line))
        body = _body(line) if numbered else line
        if not numbered:
            peeled, leftover = _peel_leading_ingredients(body)
            if peeled and leftover:
                lines.extend(peeled)
                lines.append(leftover)
                continue
            if len(peeled) >= 2 and not leftover:
                lines.extend(peeled)
                continue
            comma_parts = _split_ingredient_commas(body)
            if comma_parts:
                lines.extend(comma_parts)
                continue
        lines.append(line)
    return lines


def _title_from_caption(caption: str) -> str:
    for raw in caption.replace("\r", "").splitlines():
        line = _clean_line(_BULLET.sub("", raw))
        if not line or _is_skip(line):
            continue
        if _ING_HEAD.match(line) or _STEP_HEAD.match(line) or _TIP_HEAD.match(line) or _GROUP_HEAD.match(line):
            continue
        if looks_like_step(line) or _UNIT_AT_START.match(line):
            continue
        if len(_tokens(line)) <= 10:
            return line[:80]
    return ""


def pick_title(title: str, caption: str) -> str:
    cleaned = _clean_line(title.split("\n")[0])[:80]
    fallback = _title_from_caption(caption)
    if not cleaned or _GENERIC_TITLE.match(cleaned) or cleaned.lower().startswith("http"):
        return fallback or cleaned or "recipe"
    return cleaned or fallback or "recipe"


def _split_numbered_inline(item: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?=\d+[\.)]\s+)", item) if part.strip()]
    if len(parts) >= 2 and all(_NUMBER.match(part) or looks_like_step(part) for part in parts):
        return [_body(part) for part in parts]
    return [item]


def _norm_amount_token(raw: str) -> str:
    text = re.sub(r"\s+", "", raw.lower())
    text = re.sub(r"^ca\.?", "", text)
    for source, target in (
        ("kilogramm", "kg"),
        ("milliliter", "ml"),
        ("gramm", "g"),
        ("grams", "g"),
        ("liter", "l"),
        ("tbsp", "el"),
        ("tbs", "el"),
        ("tsp", "tl"),
        ("cups", "cup"),
    ):
        if text.endswith(source):
            text = text[: -len(source)] + target
            break
    return text


def _item_fingerprint(item: str) -> tuple[str, set[str]]:
    match = _NEXT_AMOUNT.search(item)
    amount = _norm_amount_token(match.group(0)) if match else ""
    rest = item[match.end() :] if match else item
    names = {token for token in _tokens(rest) if token not in _FILLER and token not in _COOK_VERBS}
    return amount, names


def _names_overlap(left: set[str], right: set[str]) -> bool:
    if left & right:
        return True
    for first in left:
        for second in right:
            if first in second or second in first:
                return True
    return False


def _same_ingredient(left: str, right: str) -> bool:
    if re.sub(r"\s+", " ", left.lower()).strip() == re.sub(r"\s+", " ", right.lower()).strip():
        return True
    amount_left, names_left = _item_fingerprint(left)
    amount_right, names_right = _item_fingerprint(right)
    if amount_left and amount_right and amount_left == amount_right:
        if not names_left or not names_right:
            return True
        return _names_overlap(names_left, names_right)
    return False


def _already_listed(item: str, existing: list[str]) -> bool:
    return any(_same_ingredient(item, other) for other in existing)


def _scan_ingredient_mentions(text: str) -> list[str]:
    found: list[str] = []
    for match in _NEXT_AMOUNT.finditer(text):
        after = text[match.end() :].lstrip(" ,;/")
        if _is_time_span(after[:12]):
            continue
        name, leftover = _name_before_instruction(after)
        if leftover:
            first = _tokens(leftover)
            if first and first[0] in _COOK_VERBS and not name:
                continue
        chunk = f"{match.group(0)} {name}".strip(" ,;.")
        if not name or not _AMOUNT_WITH_UNIT.match(chunk):
            continue
        if is_instruction_prose(chunk) and _has_cook_verb(chunk):
            continue
        if not _already_listed(chunk, found):
            found.append(chunk)
    return found


def _merge_scanned_ingredients(
    groups: list[IngredientGroup], caption: str, steps: list[str], tips: list[str]
) -> list[IngredientGroup]:
    listed = [item for group in groups for item in group.items]
    extras: list[str] = []
    blob = "\n".join([caption, *steps, *tips])
    for item in _scan_ingredient_mentions(blob):
        if _already_listed(item, listed) or _already_listed(item, extras):
            continue
        extras.append(item)
    if not extras:
        return groups
    if not groups:
        return [IngredientGroup("", extras)]
    if not groups[-1].heading:
        groups[-1].items.extend(extras)
        return groups
    groups.append(IngredientGroup("", extras))
    return groups


def parse_caption(title: str, handle: str, url: str, caption: str) -> RecipeDraft:
    groups: list[IngredientGroup] = []
    steps: list[str] = []
    tips: list[str] = []
    current: list[str] = []
    heading = ""
    mode = "auto"
    chosen_title = pick_title(title, caption)
    lines = _normalize_lines(caption)
    for index, line in enumerate(lines):
        nxt = next((item for item in lines[index + 1 :] if item), "")
        if not line:
            if mode in {"ingredients", "auto"} and current:
                groups.append(IngredientGroup(heading, current))
                current, heading = [], ""
            continue
        key = line.lower().rstrip(":")
        if _STEP_HEAD.match(key):
            if current:
                groups.append(IngredientGroup(heading, current))
                current, heading = [], ""
            mode = "steps"
            continue
        if _TIP_HEAD.match(key):
            if current:
                groups.append(IngredientGroup(heading, current))
                current, heading = [], ""
            mode = "tips"
            continue
        if _ING_HEAD.match(key):
            if current:
                groups.append(IngredientGroup(heading, current))
                current, heading = [], ""
            mode = "ingredients"
            continue
        if mode in {"auto", "ingredients"} and _clean_line(line)[:80] == chosen_title:
            continue
        in_list = mode == "ingredients" or bool(current)
        group_heading = (
            mode not in {"steps", "tips"}
            and not _UNIT_AT_START.match(line)
            and not is_instruction_prose(line)
            and (
                _GROUP_HEAD.match(key)
                or (line.endswith(":") and not looks_like_ingredient(line, in_list=in_list))
                or (
                    bool(current)
                    and looks_like_ingredient(nxt, in_list=True)
                    and len(_tokens(line)) <= 4
                    and not looks_like_ingredient(line, in_list=True)
                )
            )
        )
        if group_heading:
            if current:
                groups.append(IngredientGroup(heading, current))
                current = []
            heading = line.rstrip(":")
            mode = "ingredients"
            continue
        item = _body(line)
        if mode == "tips":
            tips.append(item)
            continue
        if mode == "steps":
            steps.extend(_split_numbered_inline(item))
            continue
        as_ingredient = looks_like_ingredient(line, in_list=in_list)
        as_step = looks_like_step(line)
        if mode == "auto" and not as_ingredient and not as_step and not _NUMBER.match(line):
            continue
        if as_ingredient and not as_step:
            mode = "ingredients"
            current.append(item)
            continue
        if as_step:
            if current:
                groups.append(IngredientGroup(heading, current))
                current, heading = [], ""
            mode = "steps"
            steps.extend(_split_numbered_inline(item))
            continue
        if mode == "ingredients":
            current.append(item)
            continue
        if current:
            groups.append(IngredientGroup(heading, current))
            current, heading = [], ""
        mode = "steps"
        steps.extend(_split_numbered_inline(item))
    if current:
        groups.append(IngredientGroup(heading, current))
    groups = [group for group in groups if group.items or group.heading]
    groups = _merge_scanned_ingredients(groups, caption, steps, tips)
    display_handle = handle if handle.startswith("Insta:") or not handle else f"Insta: {handle}"
    notes = caption if (not groups or not steps) else ""
    return RecipeDraft(
        title=chosen_title,
        handle=display_handle,
        url=url,
        image_name="cover.jpg",
        groups=groups,
        steps=steps,
        tips=tips,
        notes=notes,
    )


def _strip_bullet(line: str) -> str:
    return _BULLET.sub("", line).strip()


def _is_section_heading(line: str) -> bool:
    if line.endswith(":"):
        return True
    if _SERVINGS.match(line) or _ING_HEAD.match(line) or _GROUP_HEAD.match(line):
        return True
    if _FOR_HEAD.match(line) and not _AMOUNT_WITH_UNIT.match(line) and not _AMOUNT.match(line):
        return True
    return False


def _is_ingredient_line(line: str) -> bool:
    body = _strip_bullet(line)
    if not body or _SERVINGS.match(body):
        return False
    if _BULLET.match(line):
        return True
    return bool(_AMOUNT_WITH_UNIT.match(body) or _AMOUNT.match(body) or _TASTE.match(body))


def groups_from_text(text: str) -> list[IngredientGroup]:
    groups: list[IngredientGroup] = []
    heading = ""
    items: list[str] = []

    def close() -> None:
        nonlocal heading, items
        if items:
            groups.append(IngredientGroup(heading, items))
        heading, items = "", []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if items:
                close()
            continue
        body = _strip_bullet(line)
        if not body:
            continue
        if _is_section_heading(body) and not _is_ingredient_line(line):
            name = body.rstrip(":").strip()
            if items:
                close()
                heading = name
            elif heading and _SERVINGS.match(heading):
                heading = f"{heading} · {name}"
            else:
                heading = name
            continue
        items.append(body)
    close()
    return groups


def format_ingredients(groups: list[IngredientGroup]) -> str:
    blocks: list[str] = []
    for group in groups:
        if group.heading:
            blocks.append(group.heading)
        blocks.extend(f"- {item}" for item in group.items)
        blocks.append("")
    return "\n".join(blocks).strip()


def format_steps(steps: list[str], tips: list[str], language: str = "de") -> str:
    lines = list(steps)
    if tips:
        if lines:
            lines.append("")
        lines.append("Tipps" if language == "de" else "Tips")
        lines.extend(f"- {tip}" for tip in tips)
    return "\n".join(lines)


def steps_from_text(text: str) -> tuple[list[str], list[str]]:
    steps: list[str] = []
    tips: list[str] = []
    mode = "steps"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        key = line.lower().rstrip(":")
        if _TIP_HEAD.match(key) and not _AMOUNT.match(line):
            mode = "tips"
            continue
        item = _BULLET.sub("", line)
        item = _NUMBER.sub("", item).strip() or line
        if mode == "tips":
            tips.append(item)
        else:
            steps.append(item)
    return steps, tips
