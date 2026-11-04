"""Stage 8: import statuses and answers entered by the human in Excel."""
from openpyxl import load_workbook

from pipeline.case_store import CaseStore
from pipeline.models import HumanValidationRecord, HumanValidationResult


def run(store: CaseStore) -> HumanValidationResult:
    workbook_path = store.artifact_path("validation_workbook.xlsx")
    if not workbook_path.exists():
        raise FileNotFoundError("Validation workbook not found. Run stage 8 first.")
    sheet = load_workbook(workbook_path, data_only=False)["Validation Matrix"]
    records = []
    missing_statuses = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        requirement_id, status, notes, answer = row[0], row[10], row[11], row[12]
        if requirement_id and not status:
            missing_statuses.append(requirement_id)
        elif requirement_id:
            records.append(HumanValidationRecord(
                requirement_id=requirement_id,
                validation_status=status,
                human_notes=notes,
                client_answer=answer,
            ))
    if missing_statuses:
        raise ValueError(
            "Complete the Human Status dropdown for every requirement before continuing: "
            + ", ".join(missing_statuses)
        )
    result = HumanValidationResult(records=records)
    store.save_stage(8, result)
    return result