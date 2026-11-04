"""Deterministic assumption handling for unattended pipeline runs."""
from __future__ import annotations

from openpyxl import load_workbook

from pipeline.case_store import CaseStore
from pipeline.models import DataNeedSpecification, RequirementRetrieval, TranscriptAnalysis


AUTOMATED_NOTE = "Automated assumption; customer verification was not performed."


def answer_transcript_questions(store: CaseStore, analysis: TranscriptAnalysis) -> TranscriptAnalysis:
    """Fill unanswered stage-3 questions without pretending they are client decisions."""
    for question in analysis.clarification_questions:
        if not question.answer:
            if question.options:
                question.answer = f"Assumed option: {question.options[0]}. {AUTOMATED_NOTE}"
            else:
                question.answer = f"Proceed using the evidence available in the transcript. {AUTOMATED_NOTE}"
    store.save_stage(3, analysis)
    from pipeline.stage3_transcript_analysis import _render_report
    store.save_transcript_analysis_report(_render_report(analysis))
    return analysis


def fill_validation_workbook(store: CaseStore) -> None:
    """Populate the workbook with auditable metadata-only validation assumptions."""
    path = store.artifact_path("validation_workbook.xlsx")
    workbook = load_workbook(path)
    matrix = workbook["Validation Matrix"]
    for row in matrix.iter_rows(min_row=2):
        requirement_id = row[0].value
        if not requirement_id:
            continue
        has_mapping = bool(row[7].value)
        row[10].value = "Available" if has_mapping else "Unclear"
        row[11].value = (
            "Automated metadata mapping found; source data was not queried."
            if has_mapping
            else "No metadata mapping was available; customer confirmation is required."
        )
        row[12].value = AUTOMATED_NOTE

    gaps = workbook["Gaps & Clarifications"]
    for row in gaps.iter_rows(min_row=2):
        if row[1].value and not row[2].value:
            row[2].value = (
                f"Automated assumption: retain the documented requirement and flag it for customer "
                f"confirmation during delivery. {AUTOMATED_NOTE}"
            )
    workbook.save(path)


class OfflineRulebookClient:
    """Rulebook fallback used only by unattended mock runs."""

    @staticmethod
    def _results(requirements):
        return [
            (
                RequirementRetrieval(
                    requirement_id=requirement.requirement_id,
                    queries=[requirement.description],
                    grounding_status="NO_MATCH",
                    message="Offline unattended run; no RAG service was configured.",
                ),
                [],
            )
            for requirement in requirements
        ]

    def retrieve_many(self, requirements):
        return self._results(requirements)

    def retrieve_many_sync(self, requirements):
        return self._results(requirements)


def automated_schema(data_needs: DataNeedSpecification) -> dict[str, list[dict[str, str]]]:
    """Create a clearly synthetic schema so offline runs can still produce a workbook."""
    fields = [{"name": "record_id", "type": "string"}]
    seen = {"record_id"}
    for need in data_needs.needs:
        for concept in need.data_concepts:
            name = concept.concept.strip().replace(" ", "_")[:80] or "concept"
            if name not in seen:
                fields.append({"name": name, "type": "unknown"})
                seen.add(name)
    return {"Automated_Validation_View": fields}
