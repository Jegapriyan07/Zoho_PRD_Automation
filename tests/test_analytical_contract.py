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


if __name__ == "__main__":
    unittest.main()
