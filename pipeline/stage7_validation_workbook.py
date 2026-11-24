"""Stage 7: requirement-specific data-mapping workbook.

Builds one worksheet per report table found in the finalized requirements
(Report Column / Sources / Logic), then a Questions, Summary, and
Missing/Not-Available overview, and finally the human-facing validation
sheets (Human Validation, Instructions) last. There is no knowledge-base
or rulebook citation content in this workbook; "Sources" always means
where the data lives in the customer's Zoho workspace, never a transcript
or document reference.
"""
import re
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from pipeline.case_store import CaseStore
from pipeline.models import (
    AtomicRequirement,
    CandidateQuery,
    DataNeed,
    DataNeedSpecification,
    GapAnalysis,
    ReportRequirement,
    RequirementBaseline,
    RequirementDecomposition,
    SQLDiscovery,
    TranscriptAnalysis,
)

STATUS_OPTIONS = "Available,Missing,Soiled Data,Partially Available,Unclear"
NOT_LOCATED = "Not located in the current Zoho workspace metadata."
GENERAL_TABLE_NAME = "General Requirements"
UNNAMED_TABLE_NAME = "All Requirements"
MAPPED_STATUSES = {"DIRECT MATCH", "POTENTIAL MATCH", "DERIVABLE", "PARTIAL MATCH"}

HEADER_FILL = "1F365C"

TABLE_HEADERS = [
    "Requirement ID", "Report Column", "Sources", "Logic", "Mapping Status", "Acceptance Criteria",
]
QUESTIONS_HEADERS = ["Report Table", "Requirement ID", "Question", "Priority", "Answer"]
SUMMARY_HEADERS = [
    "Report Table", "Purpose", "Grain", "Total Columns", "Mapped", "Missing", "Readiness",
]
MISSING_HEADERS = [
    "Report Table", "Requirement ID", "Report Column", "Reason", "Recommended Action",
]
HUMAN_HEADERS = [
    "Requirement ID", "Report Table", "Report Column", "Sources", "Human Status", "Human Notes",
    "Client Clarification / Answer",
]

_INVALID_SHEET_CHARS = re.compile(r"[\\/*?:\[\]]")


def column_map(sheet) -> dict[str, int]:
    """Map header names to 0-based indexes so readers survive column additions."""
    return {cell.value: index for index, cell in enumerate(sheet[1]) if cell.value}


def _normalize(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower()) if text else ""


def _safe_sheet_name(name: str, used: set[str]) -> str:
    cleaned = _INVALID_SHEET_CHARS.sub("-", name).strip() or "Sheet"
    cleaned = cleaned[:31]
    candidate = cleaned
    suffix = 2
    while candidate.lower() in used:
        trimmed = cleaned[: 31 - len(f" ({suffix})")]
        candidate = f"{trimmed} ({suffix})"
        suffix += 1
    used.add(candidate.lower())
    return candidate


def _style_header_row(sheet, row: int, num_cols: int) -> None:
    fill = PatternFill("solid", fgColor=HEADER_FILL)
    for col in range(1, num_cols + 1):
        cell = sheet.cell(row=row, column=col)
        cell.fill = fill
        cell.font = Font(color="FFFFFF", bold=True)
    sheet.freeze_panes = sheet.cell(row=row + 1, column=1).coordinate


def _apply_common_formatting(sheet, header_row: int, last_row: int, num_cols: int) -> None:
    if last_row >= header_row:
        last_col_letter = get_column_letter(num_cols)
        sheet.auto_filter.ref = f"A{header_row}:{last_col_letter}{last_row}"
    for row in range(header_row + 1, last_row + 1):
        sheet.row_dimensions[row].height = 60
        for col in range(1, num_cols + 1):
            cell = sheet.cell(row=row, column=col)
            cell.alignment = Alignment(wrap_text=True, vertical="top")


def _set_column_widths(sheet, widths: dict[int, int]) -> None:
    for col_index, width in widths.items():
        sheet.column_dimensions[get_column_letter(col_index)].width = width


def _is_mapped(queries: list[CandidateQuery]) -> bool:
    return any(query.mapping_status in MAPPED_STATUSES for query in queries)


def _sources_text(requirement: AtomicRequirement, queries: list[CandidateQuery]) -> str:
    """Where this data actually lives in the customer's Zoho workspace, not a transcript reference."""
    parts = []
    if requirement.source_systems:
        parts.append("System(s): " + "; ".join(requirement.source_systems))
    paths = list(dict.fromkeys(path for query in queries for path in query.metadata_paths))
    if paths:
        parts.append("Field(s): " + "; ".join(paths))
    return "\n".join(parts) if parts else NOT_LOCATED


def _logic_text(requirement: AtomicRequirement, need: DataNeed | None) -> str:
    lines = [f"[{requirement.category}] {requirement.description}"]
    if need:
        for concept in need.data_concepts:
            if concept.metric_formula:
                lines.append(f"Formula ({concept.concept}): {concept.metric_formula}")
            elif concept.notes:
                lines.append(f"{concept.concept}: {concept.notes}")
    return "\n".join(lines)


def _mapping_status_text(queries: list[CandidateQuery]) -> str:
    if not queries:
        return "UNVERIFIED"
    statuses = {query.mapping_status for query in queries}
    if len(statuses) == 1:
        return next(iter(statuses))
    return "; ".join(sorted(statuses))


def _group_requirements(
    reports: list[ReportRequirement], requirements: list[AtomicRequirement]
) -> list[tuple[str, ReportRequirement | None, list[AtomicRequirement]]]:
    """Group atomic requirements under the report table(s) they belong to.

    Matching uses AtomicRequirement.report_surfaces (assigned during decomposition,
    which is given the same report definitions as context) against ReportRequirement.name.
    """
    if not reports:
        return [(UNNAMED_TABLE_NAME, None, list(requirements))]

    groups: list[tuple[str, ReportRequirement | None, list[AtomicRequirement]]] = [
        (report.name, report, []) for report in reports
    ]
    norm_names = [_normalize(report.name) for report in reports]
    unassigned: list[AtomicRequirement] = []
    for requirement in requirements:
        matched_indexes: set[int] = set()
        for surface in requirement.report_surfaces:
            surface_norm = _normalize(surface)
            if not surface_norm:
                continue
            for idx, report_norm in enumerate(norm_names):
                if report_norm and (report_norm in surface_norm or surface_norm in report_norm):
                    matched_indexes.add(idx)
        if matched_indexes:
            for idx in matched_indexes:
                groups[idx][2].append(requirement)
        else:
            unassigned.append(requirement)
    if unassigned:
        groups.append((GENERAL_TABLE_NAME, None, unassigned))
    return groups


def _write_table_sheet(
    workbook: Workbook,
    used: set[str],
    index: int,
    name: str,
    report: ReportRequirement | None,
    requirements: list[AtomicRequirement],
    data_needs_by_id: dict[str, DataNeed],
    queries_by_id: dict[str, list[CandidateQuery]],
) -> None:
    sheet = workbook.create_sheet(_safe_sheet_name(f"{index}. {name}", used))
    num_cols = len(TABLE_HEADERS)

    sheet.cell(row=1, column=1, value=f"Report Table: {name}").font = Font(bold=True, size=13)
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=num_cols)
    row_cursor = 2
    if report:
        info_lines = [
            ("Purpose", report.purpose),
            ("Grain", report.grain or ""),
            ("Filters", "; ".join(report.filters)),
            ("Business Rules", "; ".join(report.business_rules)),
        ]
        for label, value in info_lines:
            if not value:
                continue
            sheet.cell(row=row_cursor, column=1, value=label).font = Font(bold=True)
            sheet.cell(row=row_cursor, column=2, value=value)
            sheet.merge_cells(start_row=row_cursor, start_column=2, end_row=row_cursor, end_column=num_cols)
            row_cursor += 1
        row_cursor += 1

    header_row = row_cursor
    for col_index, header in enumerate(TABLE_HEADERS, start=1):
        sheet.cell(row=header_row, column=col_index, value=header)
    _style_header_row(sheet, header_row, num_cols)

    data_start = header_row + 1
    for offset, requirement in enumerate(requirements):
        row = data_start + offset
        need = data_needs_by_id.get(requirement.requirement_id)
        queries = queries_by_id.get(requirement.requirement_id, [])
        sheet.cell(row=row, column=1, value=requirement.requirement_id)
        sheet.cell(row=row, column=2, value=requirement.title)
        sheet.cell(row=row, column=3, value=_sources_text(requirement, queries))
        sheet.cell(row=row, column=4, value=_logic_text(requirement, need))
        sheet.cell(row=row, column=5, value=_mapping_status_text(queries))
        sheet.cell(row=row, column=6, value="\n".join(requirement.acceptance_criteria))
    last_row = data_start + len(requirements) - 1 if requirements else header_row
    _apply_common_formatting(sheet, header_row, last_row, num_cols)
    _set_column_widths(sheet, {1: 16, 2: 30, 3: 42, 4: 48, 5: 20, 6: 40})


def _write_questions_sheet(
    workbook: Workbook,
    used: set[str],
    requirements: list[AtomicRequirement],
    requirement_tables: dict[str, list[str]],
    transcript_analysis: TranscriptAnalysis | None,
) -> None:
    sheet = workbook.create_sheet(_safe_sheet_name("Questions", used))
    for col_index, header in enumerate(QUESTIONS_HEADERS, start=1):
        sheet.cell(row=1, column=col_index, value=header)
    _style_header_row(sheet, 1, len(QUESTIONS_HEADERS))

    row = 2
    seen_questions: set[str] = set()
    for requirement in requirements:
        table_name = "; ".join(requirement_tables.get(requirement.requirement_id, [])) or GENERAL_TABLE_NAME
        for question in requirement.clarification_questions:
            if question in seen_questions:
                continue
            seen_questions.add(question)
            sheet.cell(row=row, column=1, value=table_name)
            sheet.cell(row=row, column=2, value=requirement.requirement_id)
            sheet.cell(row=row, column=3, value=question)
            sheet.cell(row=row, column=4, value="Review")
            sheet.cell(row=row, column=5, value="")
            row += 1
    if transcript_analysis:
        for item in transcript_analysis.clarification_questions:
            if item.question in seen_questions:
                continue
            seen_questions.add(item.question)
            sheet.cell(row=row, column=1, value=GENERAL_TABLE_NAME)
            sheet.cell(row=row, column=2, value="; ".join(item.related_topics))
            sheet.cell(row=row, column=3, value=item.question)
            sheet.cell(row=row, column=4, value=item.priority)
            sheet.cell(row=row, column=5, value=item.answer or "")
            row += 1
    last_row = row - 1 if row > 2 else 1
    _apply_common_formatting(sheet, 1, last_row, len(QUESTIONS_HEADERS))
    _set_column_widths(sheet, {1: 26, 2: 20, 3: 70, 4: 16, 5: 50})


def _write_summary_sheet(
    workbook: Workbook,
    used: set[str],
    table_groups: list[tuple[str, ReportRequirement | None, list[AtomicRequirement]]],
    queries_by_id: dict[str, list[CandidateQuery]],
) -> None:
    sheet = workbook.create_sheet(_safe_sheet_name("Summary", used))
    for col_index, header in enumerate(SUMMARY_HEADERS, start=1):
        sheet.cell(row=1, column=col_index, value=header)
    _style_header_row(sheet, 1, len(SUMMARY_HEADERS))

    row = 2
    total_columns = total_mapped = total_missing = 0
    for name, report, requirements in table_groups:
        mapped = sum(1 for r in requirements if _is_mapped(queries_by_id.get(r.requirement_id, [])))
        missing = len(requirements) - mapped
        total_columns += len(requirements)
        total_mapped += mapped
        total_missing += missing
        if requirements and missing == 0:
            readiness = "Ready"
        elif mapped == 0:
            readiness = "Blocked"
        else:
            readiness = "Partially Ready"
        sheet.cell(row=row, column=1, value=name)
        sheet.cell(row=row, column=2, value=report.purpose if report else "")
        sheet.cell(row=row, column=3, value=report.grain if report else "")
        sheet.cell(row=row, column=4, value=len(requirements))
        sheet.cell(row=row, column=5, value=mapped)
        sheet.cell(row=row, column=6, value=missing)
        sheet.cell(row=row, column=7, value=readiness)
        row += 1

    sheet.cell(row=row, column=1, value="TOTAL").font = Font(bold=True)
    sheet.cell(row=row, column=4, value=total_columns).font = Font(bold=True)
    sheet.cell(row=row, column=5, value=total_mapped).font = Font(bold=True)
    sheet.cell(row=row, column=6, value=total_missing).font = Font(bold=True)
    last_row = row
    _apply_common_formatting(sheet, 1, last_row, len(SUMMARY_HEADERS))
    _set_column_widths(sheet, {1: 30, 2: 44, 3: 20, 4: 14, 5: 12, 6: 12, 7: 18})
    sheet.cell(row=row + 2, column=1, value=f"Total report tables: {len(table_groups)}")


def _write_missing_sheet(
    workbook: Workbook,
    used: set[str],
    requirements: list[AtomicRequirement],
    requirement_tables: dict[str, list[str]],
    queries_by_id: dict[str, list[CandidateQuery]],
) -> None:
    sheet = workbook.create_sheet(_safe_sheet_name("Missing - Not Available", used))
    for col_index, header in enumerate(MISSING_HEADERS, start=1):
        sheet.cell(row=1, column=col_index, value=header)
    _style_header_row(sheet, 1, len(MISSING_HEADERS))

    row = 2
    for requirement in requirements:
        table_name = "; ".join(requirement_tables.get(requirement.requirement_id, [])) or GENERAL_TABLE_NAME
        queries = queries_by_id.get(requirement.requirement_id, [])
        if not _is_mapped(queries):
            rationale = "; ".join(query.mapping_rationale for query in queries if query.mapping_rationale)
            reason = rationale or "No metadata path was found in the current Zoho workspace for this requirement."
            sheet.cell(row=row, column=1, value=table_name)
            sheet.cell(row=row, column=2, value=requirement.requirement_id)
            sheet.cell(row=row, column=3, value=requirement.title)
            sheet.cell(row=row, column=4, value=reason)
            sheet.cell(
                row=row, column=5,
                value="Confirm with the client whether this data exists elsewhere, or scope a new field/table to capture it.",
            )
            row += 1
        for info in requirement.missing_information:
            sheet.cell(row=row, column=1, value=table_name)
            sheet.cell(row=row, column=2, value=requirement.requirement_id)
            sheet.cell(row=row, column=3, value=requirement.title)
            sheet.cell(row=row, column=4, value=info)
            sheet.cell(row=row, column=5, value="Clarify with the client and update this workbook once resolved.")
            row += 1
    last_row = row - 1 if row > 2 else 1
    _apply_common_formatting(sheet, 1, last_row, len(MISSING_HEADERS))
    _set_column_widths(sheet, {1: 26, 2: 16, 3: 30, 4: 55, 5: 50})


def _write_human_validation_sheet(
    workbook: Workbook,
    used: set[str],
    requirements: list[AtomicRequirement],
    requirement_tables: dict[str, list[str]],
    queries_by_id: dict[str, list[CandidateQuery]],
) -> None:
    sheet = workbook.create_sheet(_safe_sheet_name("Human Validation", used))
    for col_index, header in enumerate(HUMAN_HEADERS, start=1):
        sheet.cell(row=1, column=col_index, value=header)
    _style_header_row(sheet, 1, len(HUMAN_HEADERS))

    row = 2
    for requirement in requirements:
        table_name = "; ".join(requirement_tables.get(requirement.requirement_id, [])) or GENERAL_TABLE_NAME
        queries = queries_by_id.get(requirement.requirement_id, [])
        sheet.cell(row=row, column=1, value=requirement.requirement_id)
        sheet.cell(row=row, column=2, value=table_name)
        sheet.cell(row=row, column=3, value=requirement.title)
        sheet.cell(row=row, column=4, value=_sources_text(requirement, queries))
        row += 1
    last_row = row - 1

    if last_row >= 2:
        columns = column_map(sheet)
        status_letter = get_column_letter(columns["Human Status"] + 1)
        validation = DataValidation(type="list", formula1=f'"{STATUS_OPTIONS}"', allow_blank=True)
        validation.error = "Choose a status from the list."
        sheet.add_data_validation(validation)
        validation.add(f"{status_letter}2:{status_letter}{last_row}")
    _apply_common_formatting(sheet, 1, max(last_row, 1), len(HUMAN_HEADERS))
    _set_column_widths(sheet, {1: 16, 2: 26, 3: 30, 4: 42, 5: 20, 6: 34, 7: 38})


def _write_instructions_sheet(workbook: Workbook, used: set[str]) -> None:
    sheet = workbook.create_sheet(_safe_sheet_name("Instructions", used))
    lines = [
        "Human Validation Workflow",
        "1. Open each report-table sheet and review the Report Column, Sources, and Logic for that table.",
        "2. Use the Sources column to locate the data in the customer's live Zoho workspace and confirm it "
        "exists, is complete, and is correctly populated. 'Sources' is always a data location, never a "
        "transcript or document reference.",
        "3. Review 'Missing - Not Available' for anything this Zoho application does not currently have, "
        "and resolve the Recommended Action for each row.",
        "4. Answer every row in 'Questions' before the PRD is generated.",
        "5. In 'Human Validation', set a Human Status for every requirement. The agent never verifies "
        "source data itself.",
        "6. Record data-quality issues as Soiled Data and explain them in Human Notes.",
        "7. Check 'Summary' for the overall readiness of each report table before sign-off.",
    ]
    for index, line in enumerate(lines, start=1):
        cell = sheet.cell(row=index, column=1, value=line)
        if index == 1:
            cell.font = Font(bold=True, size=14)
    sheet.column_dimensions["A"].width = 120


def run(
    store: CaseStore,
    decomposition: RequirementDecomposition,
    data_needs: DataNeedSpecification,
    discovery: SQLDiscovery,
    baseline: RequirementBaseline | None = None,
    transcript_analysis: TranscriptAnalysis | None = None,
) -> Path:
    data_needs_by_id = {need.requirement_id: need for need in data_needs.needs}
    queries_by_id: dict[str, list[CandidateQuery]] = {}
    for query in discovery.queries:
        queries_by_id.setdefault(query.requirement_id, []).append(query)

    reports = list(baseline.reports) if baseline and baseline.reports else []
    table_groups = _group_requirements(reports, decomposition.requirements)

    requirement_tables: dict[str, list[str]] = {}
    for name, _report, requirements in table_groups:
        for requirement in requirements:
            requirement_tables.setdefault(requirement.requirement_id, []).append(name)

    workbook = Workbook()
    workbook.remove(workbook.active)
    used_sheet_names: set[str] = set()

    for index, (name, report, requirements) in enumerate(table_groups, start=1):
        _write_table_sheet(
            workbook, used_sheet_names, index, name, report, requirements,
            data_needs_by_id, queries_by_id,
        )

    _write_questions_sheet(
        workbook, used_sheet_names, decomposition.requirements, requirement_tables, transcript_analysis,
    )
    _write_summary_sheet(workbook, used_sheet_names, table_groups, queries_by_id)
    _write_missing_sheet(
        workbook, used_sheet_names, decomposition.requirements, requirement_tables, queries_by_id,
    )
    _write_human_validation_sheet(
        workbook, used_sheet_names, decomposition.requirements, requirement_tables, queries_by_id,
    )
    _write_instructions_sheet(workbook, used_sheet_names)

    output_path = store.artifact_path("validation_workbook.xlsx")
    workbook.save(output_path)
    return output_path


def append_gap_questions(store: CaseStore, gap_analysis: GapAnalysis) -> Path:
    """Append LLM-generated follow-up questions to the Questions worksheet."""
    output_path = store.artifact_path("validation_workbook.xlsx")
    workbook = load_workbook(output_path)
    if "Questions" in workbook.sheetnames:
        sheet = workbook["Questions"]
    else:
        sheet = workbook.create_sheet("Questions")
        for col_index, header in enumerate(QUESTIONS_HEADERS, start=1):
            sheet.cell(row=1, column=col_index, value=header)
        _style_header_row(sheet, 1, len(QUESTIONS_HEADERS))

    existing_questions = {row[2] for row in sheet.iter_rows(min_row=2, values_only=True) if row[2]}
    next_row = sheet.max_row + 1
    for question in gap_analysis.clarification_questions:
        if question.question in existing_questions:
            continue
        sheet.cell(row=next_row, column=1, value=question.topic or GENERAL_TABLE_NAME)
        sheet.cell(row=next_row, column=2, value=", ".join(question.related_requirement_ids))
        sheet.cell(row=next_row, column=3, value=question.question)
        sheet.cell(row=next_row, column=4, value="Review")
        sheet.cell(row=next_row, column=5, value="")
        existing_questions.add(question.question)
        next_row += 1
    workbook.save(output_path)
    return output_path
