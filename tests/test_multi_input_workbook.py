import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from pipeline import stage1_intake, stage2_parsing, stage7_validation_workbook, stage8_human_validation
from pipeline.models import (
    AtomicRequirement,
    CaseContext,
    DataNeedSpecification,
    RequirementDecomposition,
    SQLDiscovery,
)


class FakeVisionClient:
    def __init__(self):
        self.images = []

    def extract_image_text(self, system_prompt, user_prompt, image_path):
        self.images.append(image_path.name)
        return f"REQ text from {image_path.name}"


class MultiInputTests(unittest.TestCase):
    def test_three_transcripts_and_three_requirement_images_are_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcripts = []
            for i in range(1, 4):
                path = root / f"call{i}.txt"
                path.write_text(f"transcript {i}", encoding="utf-8")
                transcripts.append(str(path))
            images = []
            for i in range(1, 4):
                path = root / f"req{i}.png"
                path.write_bytes(b"\x89PNG")
                images.append(str(path))

            _, store = stage1_intake.create_case(transcripts, images, base_dir=str(root / "cases"))
            client = FakeVisionClient()
            context = stage2_parsing.run(store, lambda: client)
            self.assertEqual(len(context.transcripts), 3)
            self.assertEqual([d.filename for d in context.requirement_docs], ["req1.png", "req2.png", "req3.png"])
            self.assertEqual(context.requirement_docs[0].text, "REQ text from req1.png")

            stage2_parsing.run(store, lambda: client)
            self.assertEqual(len(client.images), 3, "extracted image text must be cached on resume")

    def test_legacy_single_requirement_doc_state_loads(self):
        context = CaseContext.model_validate({
            "case_id": "c",
            "transcripts": [],
            "requirement_doc": {"filename": "r.txt", "text": "x"},
        })
        self.assertEqual([d.filename for d in context.requirement_docs], ["r.txt"])


class WorkbookColumnTests(unittest.TestCase):
    def test_workbook_groups_by_table_and_human_validation_import_works(self):
        requirement = AtomicRequirement(
            requirement_id="REQ-001",
            category="metric",
            description="Gross Profit = Revenue - direct expenses; by property and month.",
            source_reference="req1.png; call2.txt",
        )
        self.assertTrue(requirement.title.startswith("Gross Profit = Revenue"))
        self.assertLessEqual(len(requirement.title.split()), 8)
        with tempfile.TemporaryDirectory() as directory:
            store = stage1_store(directory)
            path = stage7_validation_workbook.run(
                store,
                RequirementDecomposition(requirements=[requirement]),
                DataNeedSpecification(needs=[]),
                SQLDiscovery(queries=[]),
            )
            workbook = load_workbook(path)
            self.assertIn("1. All Requirements", workbook.sheetnames)
            self.assertIn("Human Validation", workbook.sheetnames)
            self.assertNotIn("Validation Matrix", workbook.sheetnames)
            self.assertFalse(any("Knowledge Base" in name for name in workbook.sheetnames))

            table_sheet = workbook["1. All Requirements"]
            headers = [cell.value for cell in table_sheet[2]]
            self.assertEqual(
                headers,
                ["Requirement ID", "Report Column", "Sources", "Logic", "Mapping Status", "Acceptance Criteria"],
            )
            self.assertEqual(table_sheet.cell(3, 1).value, "REQ-001")

            human = workbook["Human Validation"]
            columns = stage7_validation_workbook.column_map(human)
            human.cell(2, columns["Human Status"] + 1).value = "Available"
            workbook.save(path)
            result = stage8_human_validation.run(store)
            self.assertEqual(result.records[0].validation_status, "Available")


def stage1_store(directory):
    from pipeline.case_store import CaseStore

    store = CaseStore("case", base_dir=directory)
    store.ensure_dirs()
    return store


if __name__ == "__main__":
    unittest.main()
