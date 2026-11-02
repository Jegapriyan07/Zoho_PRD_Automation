"""Shared prompt-construction helpers."""
import json
from typing import Type

from pydantic import BaseModel


def with_schema(instruction: str, model: Type[BaseModel]) -> str:
    """Append a model's JSON schema to an instruction block for a Claude system prompt."""
    schema = json.dumps(model.model_json_schema(), indent=2)
    return f"{instruction}\n\n{schema}"
