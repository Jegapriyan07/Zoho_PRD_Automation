"""Metadata-only adapter for an exported Zoho customer-workspace catalog.

The live Zoho MCP/API bridge should export the authenticated workspace metadata
to this format. This adapter deliberately has no method to query business data.
"""
import json
from pathlib import Path

from pipeline.models import WorkspaceMetadata


class MetadataFileAdapter:
    def __init__(self, metadata_path: str):
        self.metadata_path = Path(metadata_path)
        if not self.metadata_path.exists():
            raise FileNotFoundError(f"Metadata export not found: {self.metadata_path}")

    def get_metadata(self) -> WorkspaceMetadata:
        payload = self.get_catalog()
        if "entities" in payload:
            return WorkspaceMetadata.model_validate(payload)
        return WorkspaceMetadata(
            source=payload.get("source", "Zoho Analytics metadata export"),
            entities=self._entities_from_catalog(payload),
        )

    def get_catalog(self) -> dict:
        """Return the complete export, including raw endpoint responses."""
        return json.loads(self.metadata_path.read_text(encoding="utf-8"))

    @classmethod
    def _entities_from_catalog(cls, payload: dict) -> list[dict]:
        entities = []
        for workspace in payload.get("workspace_catalog", {}).values():
            for view in workspace.get("view_catalog", {}).values():
                summary = view.get("summary", {})
                details = view.get("metadata") or view.get("details") or {}
                columns = cls._find_list(details, "columns") or []
                fields = []
                for column in columns:
                    if not isinstance(column, dict):
                        continue
                    fields.append({
                        "name": column.get("columnName") or column.get("name") or "unknown",
                        "data_type": column.get("dataType") or column.get("data_type"),
                        "description": column.get("description"),
                    })
                name = summary.get("viewName") or summary.get("name")
                if name:
                    entities.append({
                        "name": name,
                        "module": "Zoho Analytics",
                        "description": summary.get("viewDesc") or summary.get("description"),
                        "fields": fields,
                        "relationships": [],
                    })
        return entities

    @staticmethod
    def _find_list(value: object, key: str) -> list | None:
        if isinstance(value, dict):
            if isinstance(value.get(key), list):
                return value[key]
            for child in value.values():
                found = MetadataFileAdapter._find_list(child, key)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = MetadataFileAdapter._find_list(child, key)
                if found is not None:
                    return found
        return None

    def as_schema(self) -> dict[str, list[dict[str, str]]]:
        metadata = self.get_metadata()
        return {
            entity.name: [
                {"name": field.name, "type": field.data_type or "unknown"}
                for field in entity.fields
            ]
            for entity in metadata.entities
        }