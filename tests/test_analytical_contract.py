import tempfile
import unittest

from pipeline.case_store import CaseStore
from pipeline.models import (
    CandidateQuery,
    DataConcept,
    DataNeed,
    DataNeedSpecification,
    GapAnalysis,
)
from pipeline.stage6_sql_discovery import run as discover_sql
from pipeline.stage3_transcript_analysis import _chunk_transcript
from pipeline.spandan_profile import baseline_payload, decomposition_payload, prd_markdown


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


if __name__ == "__main__":
    unittest.main()
