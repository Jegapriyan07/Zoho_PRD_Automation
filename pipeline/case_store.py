"""Owns a case's on-disk layout: evidence, per-stage state, and Claude call logs.

Every stage's output is saved under state/ as JSON, so any single stage can be
re-run independently by loading the previous stage's saved state instead of
re-running earlier (costly) Claude calls.
"""
import json
import shutil
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

STAGE_NAMES = {
    2: "document_parsing",
    3: "transcript_analysis",
    4: "requirement_reconciliation",
    5: "requirement_decomposition",
    6: "data_need_specification",
    65: "rulebook_retrieval",
    7: "metadata_query_design",
    9: "human_validation_import",
    10: "gap_clarification_analysis",
    11: "prd_generation",
    12: "human_acceptance",
}


class CaseStore:
    def __init__(self, case_id: str, base_dir: str = "cases"):
        self.case_id = case_id
        self.case_dir = Path(base_dir) / case_id
        self.evidence_dir = self.case_dir / "evidence"
        self.state_dir = self.case_dir / "state"
        self.logs_dir = self.case_dir / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.evidence_dir, self.state_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def copy_evidence(self, src_path: str) -> Path:
        src = Path(src_path)
        dest = self.evidence_dir / src.name
        shutil.copy2(src, dest)
        return dest

    def save_manifest(self, manifest: dict) -> Path:
        path = self.case_dir / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return path

    def load_manifest(self) -> dict:
        return json.loads((self.case_dir / "manifest.json").read_text(encoding="utf-8"))

    def _state_path(self, stage_num: int) -> Path:
        name = STAGE_NAMES.get(stage_num, f"stage_{stage_num}")
        return self.state_dir / f"{stage_num:02d}_{name}.json"

    def save_stage(self, stage_num: int, model: BaseModel) -> Path:
        path = self._state_path(stage_num)
        path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_stage(self, stage_num: int, model_cls: Type[T]) -> T:
        path = self._state_path(stage_num)
        if not path.exists():
            raise FileNotFoundError(f"No saved state for stage {stage_num} ({path}). Run that stage first.")
        return model_cls.model_validate_json(path.read_text(encoding="utf-8"))

    def has_stage(self, stage_num: int) -> bool:
        return self._state_path(stage_num).exists()

    def log_claude_call(
        self,
        stage_num: int,
        system_prompt: str,
        user_prompt: str,
        response: str,
        label: str | None = None,
    ) -> None:
        name = STAGE_NAMES.get(stage_num, f"stage_{stage_num}")
        suffix = f"_{label}" if label else ""
        path = self.logs_dir / f"{stage_num:02d}_{name}{suffix}.json"
        path.write_text(
            json.dumps(
                {
                    "stage": stage_num,
                    "stage_name": name,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "response": response,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def log_mcp_call(self, name: str, request: dict, response: dict) -> None:
        path = self.logs_dir / f"mcp_{name}.jsonl"
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps({"tool": name, "request": request, "response": response}) + "\n")

    def save_scope_document(self, markdown: str) -> Path:
        path = self.case_dir / "scope_document.md"
        path.write_text(markdown, encoding="utf-8")
        return path

    def save_prd(self, markdown: str) -> Path:
        path = self.case_dir / "prd_draft.md"
        path.write_text(markdown, encoding="utf-8")
        return path

    def save_transcript_analysis_report(self, markdown: str) -> Path:
        path = self.case_dir / "transcript_analysis_report.md"
        path.write_text(markdown, encoding="utf-8")
        return path

    def save_feedback(self, feedback: dict) -> Path:
        path = self.case_dir / "feedback.json"
        path.write_text(json.dumps(feedback, indent=2), encoding="utf-8")
        return path
