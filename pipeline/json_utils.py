"""Helpers for pulling strict JSON out of a Claude text response."""
import json
import re

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*)\n```$", re.DOTALL)


def extract_json(text: str):
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    if match:
        stripped = match.group(1).strip()
    return json.loads(stripped, strict=False)


def call_and_validate(claude, store, stage_num: int, system_prompt: str, user_prompt: str,
                      model_cls, attempts: int = 3, **call_kwargs):
    """Call the LLM and validate the reply, re-asking with the error when the JSON is malformed or off-schema."""
    from pydantic import ValidationError

    prompt = user_prompt
    for attempt in range(1, attempts + 1):
        response_text = claude.call(system_prompt, prompt, **call_kwargs)
        store.log_claude_call(stage_num, system_prompt, prompt, response_text,
                              None if attempt == 1 else f"retry{attempt - 1}")
        try:
            return model_cls.model_validate(extract_json(response_text))
        except (ValueError, ValidationError) as exc:
            if attempt == attempts:
                raise
            print(f"[Stage {stage_num}] Invalid LLM output (attempt {attempt}/{attempts}): {str(exc)[:200]}")
            prompt = (
                f"{user_prompt}\n\nYour previous reply was rejected: {str(exc)[:1500]}\n"
                "Return the complete corrected JSON only. Every string must be closed and escaped, and the "
                "reply must be shorter and fit within the output limit."
            )
