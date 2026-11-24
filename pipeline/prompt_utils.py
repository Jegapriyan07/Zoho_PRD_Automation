"""Shared prompt-construction helpers."""
import json
from typing import Type

from pydantic import BaseModel


def with_schema(instruction: str, model: Type[BaseModel]) -> str:
    """Append a model's JSON schema to an instruction block for a Claude system prompt."""
    schema = json.dumps(model.model_json_schema(), indent=2)
    return f"{instruction}\n\n{schema}"


def format_requirement_docs(docs) -> list[str]:
    """Render every authoritative requirement document/image as a labeled prompt section."""
    return [
        f"--- ORIGINAL CUSTOMER REQUIREMENT DOCUMENT {i} (AUTHORITATIVE): {doc.filename} ---\n{doc.text}"
        for i, doc in enumerate(docs, start=1)
    ]
