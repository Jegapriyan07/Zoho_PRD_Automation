"""Persist and apply stakeholder answers to transcript-analysis questions."""
from pathlib import Path

from pipeline.case_store import CaseStore
from pipeline.models import (
    TranscriptAnalysis,
    TranscriptClarificationAnswer,
    TranscriptClarificationResponse,
)
from pipeline.stage3_transcript_analysis import _render_report


def _questions_by_id(analysis: TranscriptAnalysis) -> dict[str, str]:
    questions: dict[str, str] = {}
    for item in analysis.clarification_questions:
        if item.question_id in questions:
            raise ValueError(f"Duplicate transcript clarification id: {item.question_id}")
        questions[item.question_id] = item.question
    return questions


def write_clarification_template(
    store: CaseStore, analysis: TranscriptAnalysis
) -> Path:
    """Create or refresh the case answer file, retaining answers to unchanged questions."""
    path = store.artifact_path("transcript_clarifications.json")
    questions = _questions_by_id(analysis)
    previous_answers: dict[tuple[str, str], str] = {}

    if path.exists():
        previous = TranscriptClarificationResponse.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if previous.case_id != store.case_id:
            raise ValueError(
                f"Clarification file belongs to case '{previous.case_id}', "
                f"not '{store.case_id}'."
            )
        previous_ids = [item.question_id for item in previous.answers]
        if len(previous_ids) != len(set(previous_ids)):
            raise ValueError("Clarification file contains duplicate question IDs.")
        previous_answers = {
            (item.question_id, item.question): item.answer
            for item in previous.answers
        }

    response = TranscriptClarificationResponse(
        case_id=store.case_id,
        answers=[
            TranscriptClarificationAnswer(
                question_id=question_id,
                question=question,
                answer=previous_answers.get((question_id, question), ""),
            )
            for question_id, question in questions.items()
        ],
    )
    path.write_text(response.model_dump_json(indent=2), encoding="utf-8")
    return path


def apply_clarification_answers(
    store: CaseStore, analysis: TranscriptAnalysis
) -> TranscriptAnalysis:
    """Apply answers from the case file and persist the updated analysis."""
    path = write_clarification_template(store, analysis)
    response = TranscriptClarificationResponse.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    questions = _questions_by_id(analysis)
    answers: dict[str, str] = {}

    for item in response.answers:
        if item.question_id in answers:
            raise ValueError(f"Duplicate answer for transcript question {item.question_id}.")
        if item.question_id not in questions:
            raise ValueError(f"Unknown transcript clarification id: {item.question_id}.")
        if item.question != questions[item.question_id]:
            raise ValueError(
                f"Transcript clarification {item.question_id} changed. "
                "Review the refreshed answer file before continuing."
            )
        answers[item.question_id] = item.answer.strip()

    for item in analysis.clarification_questions:
        answer = answers.get(item.question_id, "")
        item.answer = answer or None

    if analysis.clarification_questions and all(
        item.answer for item in analysis.clarification_questions
    ):
        analysis.readiness = "ready_for_reconciliation"

    store.save_stage(3, analysis)
    store.save_transcript_analysis_report(_render_report(analysis))
    return analysis


def clarification_gate_message(analysis: TranscriptAnalysis) -> str | None:
    if analysis.readiness == "needs_clarification" and not analysis.clarification_questions:
        return (
            "AI analysis marked the case as needing clarification but produced no answerable "
            "questions. Re-run stage 3 and review the transcript analysis before continuing."
        )

    unanswered = [
        item.question_id
        for item in analysis.clarification_questions
        if not item.answer or not item.answer.strip()
    ]
    if unanswered:
        return "Unanswered transcript clarification questions: " + ", ".join(unanswered)
    return None
