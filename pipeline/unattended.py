"""Deterministic assumption handling for unattended pipeline runs."""
from __future__ import annotations

from openpyxl import load_workbook

from pipeline.case_store import CaseStore
from pipeline.models import DataNeedSpecification, RequirementRetrieval, TranscriptAnalysis
from pipeline.stage7_validation_workbook import NOT_LOCATED, column_map


AUTOMATED_NOTE = "Automated assumption; customer verification was not performed."


def answer_transcript_questions(store: CaseStore, analysis: TranscriptAnalysis) -> TranscriptAnalysis:
    """Fill unanswered stage-3 questions without pretending they are client decisions."""
    for question in analysis.clarification_questions:
        if not question.answer:
            if question.options:
                question.answer = f"Assumed option: {question.options[0]}. {AUTOMATED_NOTE}"
            else:
                question.answer = f"Proceed using the evidence available in the transcript. {AUTOMATED_NOTE}"
    if analysis.clarification_questions:
        analysis.readiness = "ready_for_reconciliation"
    store.save_stage(3, analysis)
    from pipeline.stage3_transcript_analysis import _render_report
    store.save_transcript_analysis_report(_render_report(analysis))
    return analysis


def fill_validation_workbook(store: CaseStore) -> None:
    """Populate the workbook with auditable metadata-only validation assumptions."""
    path = store.artifact_path("validation_workbook.xlsx")
    workbook = load_workbook(path)
    human = workbook["Human Validation"]
    columns = column_map(human)
    id_col, sources_col = columns["Requirement ID"], columns["Sources"]
    status_col, notes_col = columns["Human Status"], columns["Human Notes"]
    answer_col = columns["Client Clarification / Answer"]
    for row in human.iter_rows(min_row=2):
        requirement_id = row[id_col].value
        if not requirement_id:
            continue
        has_mapping = bool(row[sources_col].value) and row[sources_col].value != NOT_LOCATED
        row[status_col].value = "Available" if has_mapping else "Unclear"
        row[notes_col].value = (
            "Automated metadata mapping found; source data was not queried."
            if has_mapping
            else "No metadata mapping was available; customer confirmation is required."
        )
        row[answer_col].value = AUTOMATED_NOTE

    questions = workbook["Questions"]
    questions_columns = column_map(questions)
    question_col, answer_col = questions_columns["Question"], questions_columns["Answer"]
    for row in questions.iter_rows(min_row=2):
        if row[question_col].value and not row[answer_col].value:
            row[answer_col].value = (
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
