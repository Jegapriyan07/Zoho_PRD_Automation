import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from pipeline.case_store import CaseStore
from pipeline.models import (
    CandidateQuery,
    CaseContext,
    DataConcept,
    DataNeed,
    DataNeedSpecification,
    GapAnalysis,
    TranscriptAnalysis,
    TranscriptClarificationQuestion,
)
from pipeline.stage6_sql_discovery import run as discover_sql
from pipeline.stage3_transcript_analysis import _chunk_transcript
from pipeline.spandan_profile import baseline_payload, decomposition_payload, prd_markdown
from pipeline.prd_docx_renderer import normalize_prd_markdown
from pipeline.transcript_clarification import (
    apply_clarification_answers,
    clarification_gate_message,
    write_clarification_template,
)


class AnalyticalContractTests(unittest.TestCase):
    def test_existing_gap_json_remains_loadable(self):
        gap = GapAnalysis.model_validate({
            "missing_data": [],
            "conflicting_definitions": [],
            "clarification_questions": [],
            "overall_readiness": "READY",
        })
        self.assertEqual(gap.overall_readiness, "READY")
        self.assertIsNone(gap.assessment)

    def test_candidate_query_defaults_to_unverified(self):
        query = CandidateQuery(requirement_id="REQ-001", purpose="verify", sql="")
        self.assertEqual(query.mapping_status, "UNVERIFIED")
        self.assertEqual(query.validation_status, "UNVERIFIED")

    def test_empty_metadata_never_creates_synthetic_sql(self):
        needs = DataNeedSpecification(needs=[
            DataNeed(
                requirement_id="REQ-001",
                data_concepts=[DataConcept(concept="invoice amount", concept_type="field")],
            )
        ])
        with tempfile.TemporaryDirectory() as directory:
            store = CaseStore("case", base_dir=directory)
            store.ensure_dirs()
            discovery = discover_sql(store, object(), needs, {})
            self.assertEqual(discovery.queries[0].sql, "")
            self.assertEqual(discovery.queries[0].metadata_paths, [])
            self.assertIn("not available", discovery.queries[0].mapping_rationale.lower())

    def test_large_transcript_is_split_at_readable_boundaries(self):
        chunks = _chunk_transcript(
            "meeting.txt",
            "First discussion.\n\n" + ("Shared business context. " * 120) + "\n\nFinal decision.",
            1000,
        )
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0][0], "meeting.txt#chunk-001")
        self.assertTrue(all(text.strip() for _, text in chunks))
        self.assertIn("Final decision.", chunks[-1][1])

    def test_transcript_clarification_gate_requires_answer_file(self):
        analysis = TranscriptAnalysis(
            executive_summary="Summary",
            clarification_questions=[
                TranscriptClarificationQuestion(
                    question_id="Q-001",
                    question="Which source is authoritative?",
                    ambiguity="Two sources differ.",
                    business_impact="The metric could be inconsistent.",
                    priority="blocking",
                )
            ],
            readiness="needs_clarification",
        )
        with tempfile.TemporaryDirectory() as directory:
            store = CaseStore("case", base_dir=directory)
            store.ensure_dirs()
            answer_path = write_clarification_template(store, analysis)

            updated = apply_clarification_answers(store, analysis)
            self.assertIn("Q-001", clarification_gate_message(updated))

            payload = json.loads(answer_path.read_text(encoding="utf-8"))
            payload["answers"][0]["answer"] = "Use Zoho Books."
            answer_path.write_text(json.dumps(payload), encoding="utf-8")

            updated = apply_clarification_answers(store, analysis)
            self.assertEqual(updated.clarification_questions[0].answer, "Use Zoho Books.")
            self.assertEqual(updated.readiness, "ready_for_reconciliation")
            self.assertIsNone(clarification_gate_message(updated))

    def test_transcript_clarification_gate_requires_analysis_when_marked_unresolved(self):
        analysis = TranscriptAnalysis(
            executive_summary="Summary",
            readiness="needs_clarification",
        )
        self.assertIn("produced no answerable questions", clarification_gate_message(analysis))

    def test_pipeline_blocks_stage_four_until_transcript_answers_are_saved(self):
        analysis = TranscriptAnalysis(
            executive_summary="Summary",
            clarification_questions=[
                TranscriptClarificationQuestion(
                    question_id="Q-001",
                    question="Which source is authoritative?",
                    ambiguity="Two sources differ.",
                    business_impact="The metric could be inconsistent.",
                    priority="blocking",
                )
            ],
            readiness="needs_clarification",
        )
        with tempfile.TemporaryDirectory() as directory:
            store = CaseStore("case", base_dir=directory)
            store.ensure_dirs()
            store.save_stage(2, CaseContext(case_id="case", transcripts=[]))
            store.save_stage(3, analysis)
            args = argparse.Namespace(
                from_stage=4,
                to_stage=4,
                case_id="case",
                cases_dir=directory,
                mock=True,
                unattended=False,
                transcripts=None,
                requirement=None,
            )

            import main

            output = io.StringIO()
            with redirect_stdout(output), patch.object(main.stage3_reconciliation, "run") as reconcile:
                main.run_pipeline(args)
            reconcile.assert_not_called()
            self.assertIn("[Clarification gate]", output.getvalue())

            answer_path = store.artifact_path("transcript_clarifications.json")
            payload = json.loads(answer_path.read_text(encoding="utf-8"))
            payload["answers"][0]["answer"] = "Use Zoho Books."
            answer_path.write_text(json.dumps(payload), encoding="utf-8")

            with redirect_stdout(io.StringIO()), patch.object(main.stage3_reconciliation, "run") as reconcile:
                main.run_pipeline(args)
            reconcile.assert_called_once()

    def test_spandan_profile_is_grouped_and_non_editable(self):
        baseline = baseline_payload()
        decomposition = decomposition_payload()
        self.assertEqual(len(baseline["baseline_requirements"]), 3)
        self.assertEqual(
            [item["requirement_id"] for item in decomposition["requirements"]],
            ["REQ-001", "REQ-002", "REQ-003", "REQ-004", "REQ-005"],
        )
        markdown = prd_markdown().lower()
        for forbidden in ("[editable", "editable by human", "enter effort", "enter rate"):
            self.assertNotIn(forbidden, markdown)
        for heading in (
            "## detailed requirements",
            "## delivery workflow",
            "## project cost and commercial terms",
        ):
            self.assertIn(heading, markdown)

    def test_prd_requirements_are_ordered_and_boxed(self):
        markdown = """# PRD

## Detailed Requirements
### REQ-004 — Current Assets Summary
Current assets.

### REQ-001 — Unified source consolidation
Consolidate sources.

### REQ-005 — Feasibility sample and SOW
Build a sample.
"""
        normalized = normalize_prd_markdown(markdown)
        self.assertLess(normalized.index("REQ-001"), normalized.index("REQ-004"))
        self.assertLess(normalized.index("REQ-004"), normalized.index("REQ-005"))
        self.assertIn("| Requirement | Description |", normalized)


if __name__ == "__main__":
    unittest.main()
