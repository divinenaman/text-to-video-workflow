"""Automatic voice casting — match each character to a distinct voice.

Given the character bible entries, pick voices from the voices table by
semantic similarity between the character (name + description +
voice_description) and the voice metadata (name + tags + description).
Gender is filtered BOTH on the character and voice sides, and a voice is
never reused across characters (one-voice-per-character).

Gender inference is regex-based (no LLM roundtrip); the embedding match uses
one batched gemini embed_content call and degrades gracefully when the
embedding tier is unavailable (distinct round-robin picks instead).
"""

import re

from .logger import logging
from . import text_embeddings

FEMALE_RX = re.compile(
    r"\b(female|woman|women|girl|lady|queen|princess|mother|mom|grandmother"
    r"|aunt|waitress|dancer|goddess|sister|wife|her|she)\b",
)
MALE_RX = re.compile(
    r"\b(male|man|men|boy|gentleman|lord|king|prince|father|dad|grandfather"
    r"|uncle|waiter|god|brother|husband|him|he)\b",
)


def gender_of(text: str):
    """'female' | 'male' | None — regex scan, word-boundary aware so 'woman'
    does not match the 'man' token."""
    t = (text or "").lower()
    f, m = bool(FEMALE_RX.search(t)), bool(MALE_RX.search(t))
    if f and not m:
        return "female"
    if m and not f:
        return "male"
    return None


def _gender_of_character(char) -> str | None:
    name = str(char.get("name") or "")
    # names alone are noisy signal; only trust them if description is thin
    desc = " ".join(
        str(char.get(k) or "") for k in ("description", "voice_description")
    )
    g = gender_of(desc)
    if g is None and len(desc) < 12:
        g = gender_of(name)
    return g


def _voice_query(v) -> str:
    tags = " ".join(v.tags) if isinstance(v.tags, (list, tuple)) else (v.tags or "")
    return f"{v.voice_name or ''} {tags} {v.description or ''}".strip()


def _gender_ok(char_g, voice_g):
    if not char_g or not voice_g:
        return True
    return char_g == voice_g


def _greedy(scores, chars, voices, taken_ids, char_genders, voice_genders):
    """scores: matrix [len(chars)][len(voices)]. Returns {name: voice}."""
    out = {}
    for ci, char in enumerate(chars):
        name = str(char.get("name") or "")
        if not name or name in out:
            continue
        candidates = []
        for vi, v in enumerate(voices):
            if v.id in taken_ids:
                continue
            if not _gender_ok(char_genders.get(ci), voice_genders.get(vi)):
                continue
            candidates.append((scores[ci][vi], vi))
        if not candidates:
            continue
        candidates.sort(key=lambda x: -x[0])
        best = voices[candidates[0][1]]
        out[name] = best
        taken_ids.add(best.id)
    return out


def _fallback_auto(chars, voices, taken_ids, voice_genders):
    """Distinct round-robin picks when embeddings are unavailable."""
    out = {}
    for char in chars:
        name = str(char.get("name") or "")
        if not name or name in out:
            continue
        g = _gender_of_character(char)
        eligible = [
            v for vi, v in enumerate(voices)
            if v.id not in taken_ids
            and _gender_ok(g, voice_genders[vi])
        ]
        if not eligible:
            eligible = [v for v in voices if v.id not in taken_ids]
        if not eligible:
            break
        pick = eligible[len(out) % len(eligible)]
        out[name] = pick
        taken_ids.add(pick.id)
    return out


def pick_automatic_voices(
    characters: list, voices: list, taken: dict | None = None
) -> dict:
    """Return {character_name: Voice} for characters that lack a voice.

    `taken` maps character → Voice already resolved by manual mapping; those
    voices are excluded from a reassignment. The embedding tier is given one
    shot; on failure a deterministic distinct round-robin runs instead.
    """
    already_assigned = set((taken or {}).keys())
    chars = [
        c
        for c in (characters or [])
        if isinstance(c, dict)
        and str(c.get("name") or "")
        and str(c.get("name")) not in already_assigned
    ]
    voices = [v for v in (voices or [])]
    if not chars or not voices:
        return {}

    taken_ids = {v.id for v in (taken or {}).values()}
    char_genders = {i: _gender_of_character(c) for i, c in enumerate(chars)}
    voice_texts = [_voice_query(v) for v in voices]
    voice_genders = {}
    for vi, qt in enumerate(voice_texts):
        g = gender_of(qt)
        try:
            g = g or gender_of(str(voices[vi].description or ""))
        except Exception:
            pass
        voice_genders[vi] = g

    queries = [
        f"{str(c.get('name') or '')}: {str(c.get('description') or '')} "
        f"{str(c.get('voice_description') or '')}".strip()
        for c in chars
    ]

    scores = None
    try:
        embeddings = text_embeddings.embedding_gemini(
            queries + voice_texts
        )
        if embeddings is not None and len(embeddings) >= len(queries) + len(voices):
            import numpy as np
            from sklearn.metrics.pairwise import cosine_similarity

            c_vec = np.array(embeddings[: len(queries)])
            v_vec = np.array(embeddings[len(queries):])
            scores = cosine_similarity(c_vec, v_vec)
    except Exception as e:
        logging.warning(f"voice auto-cast embeddings unavailable: {e}")

    if scores is not None:
        picked = _greedy(
            scores, chars, voices, taken_ids, char_genders, voice_genders
        )
    else:
        picked = {}

    remaining = [
        c
        for c in chars
        if str(c.get("name") or "") and str(c["name"]) not in picked
    ]
    if remaining:
        picked.update(
            _fallback_auto(remaining, voices, taken_ids, voice_genders)
        )

    logging.info(
        "voice auto-cast picks: "
        + "; ".join(
            f"{name} -> {v.id}" for name, v in picked.items()
        )
    )
    return picked
