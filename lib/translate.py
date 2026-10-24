from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import replace

from fill import IngredientGroup, RecipeDraft
from language import DE, EN, other_language

Translator = Callable[[str, str, str], str]
_PREFIX = re.compile(r"^(\[\d+\]\[\d+\]\s*)")
_MARK = re.compile(r"\[\[\s*T(\d+)\s*\]\]")
_MAX_CHUNK = 4200
_MYMEMORY_CHUNK = 450
_UA = "Mozilla/5.0 Reciplate/1.0"


class TranslateError(RuntimeError):
    pass


def pack_texts(texts: list[str]) -> str:
    return "\n".join(f"[[T{index}]]\n{text.strip()}" for index, text in enumerate(texts))


def unpack_texts(blob: str, count: int) -> list[str] | None:
    matches = list(_MARK.finditer(blob))
    if len(matches) < count:
        return None
    found: dict[int, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(blob)
        found[int(match.group(1))] = blob[start:end].strip()
    if any(index not in found or not found[index] for index in range(count)):
        return None
    return [found[index] for index in range(count)]


def _chunks(texts: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    size = 0
    for text in texts:
        extra = len(text) + 12
        if current and size + extra > _MAX_CHUNK:
            groups.append(current)
            current, size = [], 0
        current.append(text)
        size += extra
    if current:
        groups.append(current)
    return groups


_MYMEMORY_LANG = {DE: "de-DE", EN: "en-GB"}


def _google(text: str, source: str, target: str) -> str:
    from deep_translator import GoogleTranslator

    return GoogleTranslator(source=source, target=target).translate(text)


def _mymemory(text: str, source: str, target: str) -> str:
    from deep_translator import MyMemoryTranslator

    return MyMemoryTranslator(
        source=_MYMEMORY_LANG.get(source, source),
        target=_MYMEMORY_LANG.get(target, target),
    ).translate(text)


def _fetch_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def google_payload_text(payload: object) -> str:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        return ""
    parts: list[str] = []
    for item in payload[0]:
        if isinstance(item, list) and item and isinstance(item[0], str):
            parts.append(item[0])
    return "".join(parts).strip()


def _http_google(text: str, source: str, target: str) -> str:
    url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode(
        {"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": text}
    )
    translated = google_payload_text(_fetch_json(url))
    if not translated:
        raise TranslateError("Google Translate returned empty.")
    return translated


def _http_mymemory(text: str, source: str, target: str) -> str:
    pair = f"{_MYMEMORY_LANG.get(source, source)}|{_MYMEMORY_LANG.get(target, target)}"
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(
        {"q": text, "langpair": pair}
    )
    payload = _fetch_json(url)
    if not isinstance(payload, dict):
        raise TranslateError("MyMemory returned empty.")
    translated = str((payload.get("responseData") or {}).get("translatedText") or "").strip()
    if not translated:
        raise TranslateError("MyMemory returned empty.")
    return translated


def _senders() -> list[tuple[str, Translator]]:
    found: list[tuple[str, Translator]] = []
    try:
        from deep_translator import MyMemoryTranslator  # noqa: F401

        found.append(("mymemory", _mymemory))
    except Exception:
        pass
    found.append(("mymemory-http", _http_mymemory))
    try:
        from deep_translator import GoogleTranslator  # noqa: F401

        found.append(("google", _google))
    except Exception:
        pass
    found.append(("google-http", _http_google))
    return found


def _call_with_retry(send, text: str) -> str:
    last: Exception | None = None
    for delay in (0, 1.2, 2.5):
        if delay:
            time.sleep(delay)
        try:
            result = send(text)
            if result and result.strip():
                return result
        except Exception as error:
            last = error
            message = str(error).lower()
            if "too many" not in message and "429" not in message and "rate" not in message:
                break
    if last is not None:
        raise last
    raise TranslateError("Empty translation.")


def _translate_packed(texts: list[str], source: str, target: str, send) -> list[str] | None:
    packed = pack_texts(texts)
    try:
        blob = _call_with_retry(lambda _: send(packed, source, target), packed)
    except Exception:
        return None
    return unpack_texts(blob, len(texts))


def _translate_unique(texts: list[str], source: str, target: str) -> list[str]:
    senders = _senders()
    if not senders:
        raise TranslateError("No translation backend available.")
    done: list[str] = []
    last_error: Exception | None = None
    for group in _chunks(texts):
        parsed: list[str] | None = None
        packed_size = sum(len(item) for item in group) + 12 * len(group)
        for name, send in senders:
            if "mymemory" in name and packed_size > _MYMEMORY_CHUNK:
                continue
            parsed = _translate_packed(group, source, target, send)
            if parsed is not None:
                break
        if parsed is None:
            parsed = []
            for item in group:
                translated = ""
                for _name, send in senders:
                    try:
                        translated = _call_with_retry(
                            lambda value=item, fn=send: fn(value, source, target),
                            item,
                        )
                        break
                    except Exception as error:
                        last_error = error
                if not translated:
                    raise TranslateError(
                        str(last_error) if last_error else "Translation failed."
                    )
                parsed.append(translated)
        done.extend(parsed)
    if len(done) != len(texts):
        raise TranslateError("Translation came back incomplete.")
    return done


def translate_many(texts: list[str], source: str, target: str) -> dict[str, str]:
    unique = list(dict.fromkeys(item.strip() for item in texts if item.strip()))
    if not unique:
        return {}
    try:
        translated = _translate_unique(unique, source, target)
    except Exception as error:
        raise TranslateError(f"Translation failed: {error}") from error
    return dict(zip(unique, translated, strict=True))


def _title_parts(title: str) -> tuple[str, str]:
    match = _PREFIX.match(title)
    if not match:
        return "", title
    return match.group(1), title[match.end() :].strip()


def translate_draft(
    draft: RecipeDraft,
    target: str,
    *,
    translator: Translator | None = None,
) -> RecipeDraft:
    source = draft.language
    if source == target:
        return replace(draft)
    prefix, title_rest = _title_parts(draft.title)
    pieces = [title_rest]
    for group in draft.groups:
        pieces.append(group.heading)
        pieces.extend(group.items)
    pieces.extend(draft.steps)
    pieces.extend(draft.tips)

    if translator is None:
        mapping = translate_many(pieces, source, target)

        def tr(value: str) -> str:
            key = value.strip()
            return mapping.get(key, value) if key else value
    else:
        cache: dict[str, str] = {}

        def tr(value: str) -> str:
            key = value.strip()
            if not key:
                return value
            if key not in cache:
                cache[key] = translator(key, source, target)
            return cache[key]

    groups = [
        IngredientGroup(tr(group.heading) if group.heading else "", [tr(item) for item in group.items])
        for group in draft.groups
    ]
    translated_title = prefix + tr(title_rest) if title_rest else draft.title
    return replace(
        draft,
        title=translated_title,
        groups=groups,
        steps=[tr(step) for step in draft.steps],
        tips=[tr(tip) for tip in draft.tips],
        language=target,
    )


def bilingual_drafts(
    source_draft: RecipeDraft,
    *,
    translator: Translator | None = None,
) -> dict[str, RecipeDraft]:
    source = source_draft.language if source_draft.language in {DE, EN} else DE
    source_draft = replace(source_draft, language=source)
    other = other_language(source)
    kwargs = {} if translator is None else {"translator": translator}
    return {
        source: replace(source_draft),
        other: translate_draft(source_draft, other, **kwargs),
    }
