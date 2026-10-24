"""Position-preserving explicit weights, with a protected MOSS Layout JSON mode."""
from __future__ import annotations
from dataclasses import dataclass
import json
import math
import re
import unicodedata
from .config import EmphasisError, MAX_TEXT

NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")

@dataclass(frozen=True)
class Parsed:
    text: str
    weights: tuple[float, ...]
    groups: int


def _checked(w: float) -> float:
    if not math.isfinite(w) or not -2 <= w <= 4:
        raise EmphasisError("INVALID_WEIGHT", "Each explicit and nested effective weight must be finite and within -2..4.")
    return w


def _plain(text: str, budget: list[int]) -> Parsed:
    text = unicodedata.normalize("NFC", text)

    def segment(a: int, b: int, depth: int):
        if depth > 16:
            raise EmphasisError("SYNTAX_LIMIT", "Parenthesis nesting exceeds 16 levels.")
        chars, ws = [], []
        i = a
        while i < b:
            ch = text[i]
            if ch == "\\" and i + 1 < b and text[i + 1] in "():\\":
                chars.append(text[i + 1]); ws.append(1.0); i += 2
                continue
            if ch != "(":
                chars.append(ch); ws.append(1.0); i += 1
                continue
            j, nesting, colon = i + 1, 1, None
            while j < b:
                if text[j] == "\\" and j + 1 < b and text[j + 1] in "():\\":
                    j += 2; continue
                if text[j] == "(":
                    nesting += 1
                    if depth + nesting > 16:
                        raise EmphasisError("SYNTAX_LIMIT", "Parenthesis nesting exceeds 16 levels.")
                elif text[j] == ")":
                    nesting -= 1
                    if nesting == 0:
                        break
                elif text[j] == ":" and nesting == 1:
                    colon = j
                j += 1
            if j == b:
                if colon is not None:
                    raise EmphasisError("INVALID_WEIGHT", "Unclosed explicit weight group.")
                # Literal unmatched parentheses are common in prose and emoticons.
                chars.append("("); ws.append(1.0); i += 1
                continue
            if colon is None:
                inner, weights = segment(i + 1, j, depth + 1)
                chars.extend(["(", *inner, ")"]); ws.extend([1.0, *weights, 1.0])
            else:
                number = text[colon + 1:j].strip()
                if not NUMBER.fullmatch(number):
                    raise EmphasisError("INVALID_WEIGHT", "Expected an explicit decimal weight; escape a literal colon as \\:.")
                weight = _checked(float(number))
                budget[0] += 1
                if budget[0] > 128:
                    raise EmphasisError("SYNTAX_LIMIT", "More than 128 weighted groups.")
                inner, weights = segment(i + 1, colon, depth + 1)
                if not "".join(inner).strip():
                    raise EmphasisError("INVALID_WEIGHT", "A weighted phrase cannot be empty.")
                chars.extend(inner)
                ws.extend(_checked(w * weight) if not c.isspace() else 1.0 for c, w in zip(inner, weights))
            i = j + 1
        return chars, ws

    before = budget[0]
    chars, ws = segment(0, len(text), 0)
    return Parsed("".join(chars), tuple(ws), budget[0] - before)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EmphasisError("INVALID_LAYOUT", "Duplicate JSON keys are not supported.")
        result[key] = value
    return result


def _layout(text: str) -> Parsed:
    try:
        root = json.loads(text, object_pairs_hook=_unique, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (ValueError, RecursionError) as exc:
        raise EmphasisError("INVALID_LAYOUT", "Malformed Layout JSON; no fallback to prose parsing.") from exc
    if not isinstance(root, dict) or not isinstance(root.get("summary"), dict) or not isinstance(root.get("items"), list):
        raise EmphasisError("INVALID_LAYOUT", "JSON weighting requires MOSS summary/items layout format.")
    decoder, edits, budget = json.JSONDecoder(), [], [0]

    def space(i):
        while i < len(text) and text[i].isspace():
            i += 1
        return i

    def walk(i, path, depth):
        if depth > 64:
            raise EmphasisError("SYNTAX_LIMIT", "JSON nesting exceeds 64 levels.")
        i = space(i)
        if text[i] == '"':
            value, end = decoder.raw_decode(text, i)
            allowed = path == ("summary", "caption") or (len(path) == 3 and path[0] == "items" and type(path[1]) is int and path[2] == "caption")
            if allowed:
                parsed = _plain(value, budget)
                if parsed.groups:
                    chars, weights = ['"'], [1.0]
                    for char, weight in zip(parsed.text, parsed.weights):
                        encoded = json.dumps(char, ensure_ascii=False)[1:-1]
                        chars.extend(encoded); weights.extend([weight] * len(encoded))
                    chars.append('"'); weights.append(1.0)
                    edits.append((i, end, "".join(chars), weights))
            return end
        if text[i] == "{":
            i = space(i + 1)
            while text[i] != "}":
                key, i = decoder.raw_decode(text, i)
                i = walk(space(i) + 1, path + (key,), depth + 1)
                i = space(i)
                if text[i] == ",":
                    i = space(i + 1)
            return i + 1
        if text[i] == "[":
            i, index = space(i + 1), 0
            while text[i] != "]":
                i = space(walk(i, path + (index,), depth + 1)); index += 1
                if text[i] == ",":
                    i = space(i + 1)
            return i + 1
        return decoder.raw_decode(text, i)[1]

    walk(0, (), 0)
    parts, weights, previous = [], [], 0
    for a, b, replacement, ws in edits:
        literal = text[previous:a]
        parts.extend([literal, replacement]); weights.extend([1.0] * len(literal)); weights.extend(ws)
        previous = b
    parts.append(text[previous:]); weights.extend([1.0] * (len(text) - previous))
    return Parsed("".join(parts), tuple(weights), budget[0])


def parse(text: str) -> Parsed:
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise EmphasisError("SYNTAX_LIMIT", f"Expected text of at most {MAX_TEXT} characters.")
    # Avoid even normalization when no explicit weight processing is needed.
    if "(" not in text or ":" not in text:
        return Parsed(text, (1.0,) * len(text), 0)
    stripped = text.lstrip()
    if stripped.startswith("({"):
        raise EmphasisError("INVALID_LAYOUT", "Weight captions, not an entire JSON object.")
    result = _layout(text) if stripped.startswith("{") else _plain(text, [0])
    return result if result.groups else Parsed(text, (1.0,) * len(text), 0)
