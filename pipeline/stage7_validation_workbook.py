"""Stage 7: create the human-owned metadata and data validation workbook."""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from pipeline.case_store import CaseStore
from pipeline.models import (
    DataNeedSpecification,
    GapAnalysis,
    RequirementDecomposition,
    RulebookRetrievalResult,
    SQLDiscovery,
)

STATUS_OPTIONS = "Available,Missing,Soiled Data,Partially Available,Unclear"
HEADERS = [
    "Requirement ID", "Finalized Requirement", "Category", "Metric / Formula",
    "Knowledge Base Reference", "Grounding Status", "Variables / Data Needed", "Metadata Path(s)",
    "Metadata Mapping Note", "Human Validation Query", "Human Status", "Human Notes",
    "Client Clarification / Answer",
    "Evidence Reference(s)", "Source System(s)", "Report Surface(s)",
    "Acceptance Criteria", "Validation Method",
]


def _style_sheet(sheet) -> None:
    header_fill = PatternFill("solid", fgColor="1F365C")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions


def run(
    store: CaseStore,
    decomposition: RequirementDecomposition,
    data_needs: DataNeedSpecification,
    discovery: SQLDiscovery,
    retrieval: RulebookRetrievalResult,
) -> Path:
    needs_by_id = {need.requirement_id: need for need in data_needs.needs}
    queries_by_id = {}
    for query in discovery.queries:
        queries_by_id.setdefault(query.requirement_id, []).append(query)
    retrieval_by_id = {item.requirement_id: item for item in retrieval.requirements}

    workbook = Workbook()
    matrix = workbook.active
    matrix.title = "Validation Matrix"
    matrix.append(HEADERS)
    _style_sheet(matrix)

    for requirement in decomposition.requirements:
        need = needs_by_id.get(requirement.requirement_id)
        concepts = need.data_concepts if need else []
        queries = queries_by_id.get(requirement.requirement_id, [])
        requirement_retrieval = retrieval_by_id.get(requirement.requirement_id)
        formulas = "\n".join(filter(None, (concept.metric_formula for concept in concepts)))
        references = "\n".join(filter(None, (concept.rulebook_reference for concept in concepts)))
        variables = "\n".join(concept.concept for concept in concepts)
        paths = "\n".join(path for query in queries for path in query.metadata_paths)
        query_text = "\n\n".join(query.sql for query in queries)
        mapping_note = "Mapped from workspace metadata." if paths else "No confirmed metadata path; clarify with customer."
        matrix.append([
            requirement.requirement_id, requirement.description, requirement.category, formulas,
            references, requirement_retrieval.grounding_status if requirement_retrieval else "ERROR",
            variables, paths, mapping_note, query_text, "", "", "",
            "\n".join(requirement.evidence),
            "\n".join(requirement.source_systems),
            "\n".join(requirement.report_surfaces),
            "\n".join(requirement.acceptance_criteria),
            requirement.validation_method or "",
        ])

    for column, width in {"A": 16, "B": 42, "C": 16, "D": 32, "E": 30, "F": 18,
                          "G": 36, "H": 36, "I": 34, "J": 58, "K": 22, "L": 34,
                          "M": 38, "N": 42, "O": 28, "P": 32, "Q": 42,
                          "R": 36}.items():
        matrix.column_dimensions[column].width = width
    for row in range(2, matrix.max_row + 1):
        matrix.row_dimensions[row].height = 60
        for cell in matrix[row]:
            cell.alignment = cell.alignment.copy(wrap_text=True, vertical="top")

    validation = DataValidation(type="list", formula1=f'"{STATUS_OPTIONS}"', allow_blank=True)
    validation.error = "Choose a status from the list."
    matrix.add_data_validation(validation)
    validation.add(f"K2:K{max(matrix.max_row, 2)}")

    citations = workbook.create_sheet("Knowledge Base Evidence")
    citations.append([
        "Requirement ID", "Chunk ID", "Category", "Article", "Heading Path",
        "Relevance Score", "Retrieval Query", "Retrieved Excerpt",
    ])
    _style_sheet(citations)
    for item in retrieval.requirements:
        for chunk in item.chunks:
            citations.append([
                item.requirement_id, chunk.chunk_id, chunk.category, chunk.title,
                chunk.heading_path, chunk.score, chunk.retrieval_query, chunk.content,
            ])
    for column, width in {"A": 18, "B": 20, "C": 34, "D": 32, "E": 42,
                          "F": 16, "G": 48, "H": 100}.items():
        citations.column_dimensions[column].width = width
    for row in range(2, citations.max_row + 1):
        citations.row_dimensions[row].height = 75
        for cell in citations[row]:
            cell.alignment = cell.alignment.copy(wrap_text=True, vertical="top")

    gaps = workbook.create_sheet("Gaps & Clarifications")
    gaps.append(["Requirement ID", "Gap / Clarification Needed", "Human / Client Answer"])
    _style_sheet(gaps)
    for row in range(2, matrix.max_row + 1):
        if matrix.cell(row, 6).value != "GROUNDED":
            gaps.append([matrix.cell(row, 1).value, "Knowledge-base evidence did not define this requirement sufficiently. Clarify the metric definition, formula, and required fields.", ""])
        if not matrix.cell(row, 8).value:
            gaps.append([matrix.cell(row, 1).value, "No metadata path was mapped. Confirm the correct Zoho module, report, and field.", ""])
        if not matrix.cell(row, 4).value:
            gaps.append([matrix.cell(row, 1).value, "No knowledge-base formula was found for this metric. Provide its calculation and inclusions/exclusions.", ""])
    gaps.column_dimensions["A"].width = 18
    gaps.column_dimensions["B"].width = 85
    gaps.column_dimensions["C"].width = 55
    for row in range(2, gaps.max_row + 1):
        gaps.row_dimensions[row].height = 45
        for cell in gaps[row]:
            cell.alignment = cell.alignment.copy(wrap_text=True, vertical="top")

    instructions = workbook.create_sheet("Instructions")
    instructions.append(["Human Validation Workflow"])
    instructions.append(["1. Review each metadata path against the customer workspace."])
    instructions.append(["2. Copy the validation query into the approved Zoho reporting/query interface."])
    instructions.append(["3. Select Human Status. The agent never verifies source data itself."])
    instructions.append(["4. Record data-quality issues as Soiled Data and explain them in Human Notes."])
    instructions.append(["5. Answer every applicable item on Gaps & Clarifications before generating the PRD."])
    instructions.column_dimensions["A"].width = 110
    instructions["A1"].font = Font(bold=True, size=14)

    output_path = store.case_dir / "validation_workbook.xlsx"
    workbook.save(output_path)
    return output_path


def append_gap_questions(store: CaseStore, gap_analysis: GapAnalysis) -> Path:
    """Append LLM-generated follow-up questions after initial human validation."""
    output_path = store.case_dir / "validation_workbook.xlsx"
    workbook = Workbook()
    if output_path.exists():
        from openpyxl import load_workbook
        workbook = load_workbook(output_path)
    gaps = workbook["Gaps & Clarifications"]
    existing_questions = {row[1] for row in gaps.iter_rows(min_row=2, values_only=True) if row[1]}
    for question in gap_analysis.clarification_questions:
        if question.question not in existing_questions:
            gaps.append([
                ", ".join(question.related_requirement_ids),
                question.question,
                "",
            ])
    workbook.save(output_path)
    return output_path