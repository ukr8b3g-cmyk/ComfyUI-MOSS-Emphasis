"""Align weights to the *actual* native MOSS byte-BPE tokens, not phrase searches."""
from __future__ import annotations
import unicodedata
from .config import EmphasisError
from .parser import Parsed

PREFIX = "<|im_start|>user\n"
SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n"


def byte_decoder():
    visible = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
    table = {chr(v): v for v in visible}
    for index, value in enumerate(v for v in range(256) if v not in visible):
        table[chr(256 + index)] = value
    return table


def normalize(parsed: Parsed) -> tuple[str, list[float]]:
    """Map canonical decompositions, including Japanese combining dakuten."""
    decomposed, weights = [], []
    for char, weight in zip(parsed.text, parsed.weights):
        part = unicodedata.normalize("NFD", char)
        decomposed.extend(part); weights.extend([weight] * len(part))
    nfc = unicodedata.normalize("NFC", parsed.text)
    if "".join(decomposed) != unicodedata.normalize("NFD", nfc):
        raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Ambiguous combining-character reordering; use NFC-normalized text.")
    out, i = [], 0
    for char in nfc:
        n = len(unicodedata.normalize("NFD", char))
        out.append(sum(weights[i:i+n]) / n); i += n
    left = len(nfc) - len(nfc.lstrip())
    end = len(nfc.rstrip())
    return nfc[left:end], out[left:end]


def align(parsed: Parsed, ids: list[int], pieces: list[str], special_tokens: set[str], decoder=None) -> list[float]:
    text, weights = normalize(parsed)
    if any(token in text for token in special_tokens if token):
        raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Explicit chat/vision special tokens are not supported in weighted prose.")
    expected = (PREFIX + text + SUFFIX).encode("utf-8")
    decoder = decoder or byte_decoder()
    raw, spans, cursor = [], [], 0
    for piece in pieces:
        try:
            part = piece.encode("utf-8") if piece in special_tokens else bytes(decoder[c] for c in piece)
        except (KeyError, TypeError) as exc:
            raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Tokenizer is not the supported Qwen byte-BPE format.") from exc
        raw.append(part); spans.append((cursor, cursor + len(part))); cursor += len(part)
    actual = b"".join(raw)
    if actual != expected:
        code = "WEIGHTED_SPAN_TRUNCATED" if expected.startswith(actual) else "TOKEN_ALIGNMENT_FAILED"
        raise EmphasisError(code, "Token bytes do not match the full native MOSS chat template. No weights were applied.")
    if len(ids) != len(pieces):
        raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Token ID/piece counts differ.")
    # Prefix and suffix have zero coverage mass, as do whitespace bytes.
    mass = [0] * len(PREFIX.encode())
    weighted = [0.0] * len(mass)
    for char, weight in zip(text, weights):
        n = len(char.encode("utf-8")); m = int(not char.isspace())
        mass.extend([m] * n); weighted.extend([m * weight] * n)
    mass.extend([0] * len(SUFFIX.encode())); weighted.extend([0.0] * len(SUFFIX.encode()))
    result = []
    for piece, (a, b) in zip(pieces, spans):
        denominator = sum(mass[a:b])
        result.append(sum(weighted[a:b]) / denominator if denominator and piece not in special_tokens else 1.0)
    return result


def tokenize(clip, parsed: Parsed):
    tokens = clip.tokenize(parsed.text)
    if not isinstance(tokens, dict) or len(tokens) != 1:
        raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Expected one native MOSS encoder stream.")
    batches = next(iter(tokens.values()))
    if len(batches) != 1 or any(type(t[0]) is not int for t in batches[0]):
        raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Multiple token chunks, embeddings and reference images are unsupported.")
    ids = [t[0] for t in batches[0]]
    if len(ids) > 4096:
        raise EmphasisError("WEIGHTED_SPAN_TRUNCATED", "Weighted prompts are limited to 4096 tokens including the template in 0.9.")
    outer = clip.tokenizer
    inner = getattr(outer, getattr(outer, "clip", ""), None)
    hf = getattr(inner, "tokenizer", None)
    if hf is None or not hasattr(hf, "convert_ids_to_tokens"):
        raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Cannot locate the native MOSS tokenizer.")
    pieces = hf.convert_ids_to_tokens(ids)
    special = set(getattr(hf, "all_special_tokens", []))
    # Some tokenizer versions expose added tokens separately.
    special.update(t for t in getattr(hf, "get_added_vocab", lambda: {})() if t.startswith("<|") and t.endswith("|>"))
    for marker in ("<|im_start|>", "<|im_end|>"):
        if marker not in special:
            raise EmphasisError("TOKEN_ALIGNMENT_FAILED", "Required MOSS special tokens are unavailable.")
    return tokens, align(parsed, ids, pieces, special, getattr(hf, "byte_decoder", None))
