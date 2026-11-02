"""Helpers for pulling strict JSON out of a Claude text response."""
import json
import re

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*)\n```$", re.DOTALL)


def extract_json(text: str):
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    if match:
        stripped = match.group(1).strip()
    return json.loads(stripped)
