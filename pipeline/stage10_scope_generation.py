"""Stage 10: generate a complete PRD from finalized evidence and validation."""
from openpyxl import load_workbook

from pipeline.case_store import CaseStore
from pipeline.claude_client import ClaudeClient
from pipeline.json_utils import call_and_validate, extract_json
from pipeline.models import (
    DataNeedSpecification,
    GapAnalysis,
    HumanValidationResult,
    RequirementBaseline,
    RequirementDecomposition,
    ScopeDocument,
)
from pipeline.prd_docx_renderer import normalize_prd_markdown, render, render_pdf
from pipeline.prompt_utils import with_schema
from pipeline.template_contract import PRD_STRUCTURE, ANALYSIS_RULES

STAGE_NUM = 11

INSTRUCTION = f"""You generate a complete, client-ready Project Requirements Document as Markdown, built from the finalized \
requirements, the validation workbook, rulebook-grounded data needs, and evidence-backed gap analysis. \
The baseline and requirements are transcript-derived; do not omit a material business rule, source, filter, \
formula, commercial term, delivery step, support commitment, or unresolved decision that appears in them.

The document MUST use exactly these top-level sections, in this order, as Markdown "##" headings.
This is the Spandan PRD template and its table of contents must not be renamed, merged, or reordered:

## Document Overview
## The Challenge
## Objectives and Success Criteria
## Scope
## Data Sources and Source-of-Truth Rules
## Our Approach / How It Works
## Data Preparation and Data Quality Gates
## Detailed Requirements
## Metric and Calculation Definitions
## Delivery Workflow
## Estimated Effort
## Project Cost and Commercial Terms
## Risks, Open Decisions and Acceptance Criteria
## The Outcome

Guidance per section:
- Begin with one H1 title that names the solution and client where known, followed by a one-line subtitle.
- Document Overview must include Purpose, What this document covers, and Intended audience.
- Objectives and Success Criteria must state measurable business outcomes and acceptance signals.
- Scope must separate in-scope, out-of-scope, assumptions, and dependencies.
- Data Sources and Source-of-Truth Rules must identify every source, its relevant tables/files, fields, ownership, intended use, and precedence.
- Our Approach / How It Works must explain the consolidated reporting layer, source precedence, and human review.
- Data Preparation and Data Quality Gates must cover integration, consolidation/blending, account grouping/remapping, tags, calculated metrics, and reconciliation controls.
- Detailed Requirements must contain five requirement cards in numeric order REQ-001 through REQ-005. \
    REQ-002, REQ-003, and REQ-004 must be named Property-Level Custom P&L, Portfolio / All-Properties Comparison, \
    and Current Assets Summary, respectively. Each report card must use one Markdown table with Report Name, \
    Columns, Filters, and Acceptance, using the exact fields and filters from the validated workbook wherever available. \
    REQ-001 and REQ-005 must also use a Markdown table, not a free-standing paragraph.
- Metric and Calculation Definitions must state formulas and unresolved denominator or source decisions.
- Delivery Workflow must use numbered steps with owner labels and effort labels. Include customer preparation, consolidation, \
    dashboard/ratio build, testing/validation, handover, training, and the stated hypercare period.
- Estimated Effort must be a table with Step, Activity, and Effort. When the evidence does not establish \
    a number, write `Determined during feasibility and recorded in the approved SOW`. Never emit editable fields,
    bracketed placeholders, or instructions for a human to complete the PRD.
- Project Cost must be a table with Item and Amount. Preserve explicit transcript terms such as the discovery fee and \
    implementation day rate. For totals not established by evidence, write `Determined from the approved feasibility estimate`.
- Treat unresolved items as explicit open decisions or feasibility gates, not editable placeholders.
- The Outcome must be a concise bullet list of measurable deliverables and business outcomes.
- Use explicit transcript facts, not generic filler. Mark mock/sample metadata and assumptions clearly as assumptions.
- Include unresolved gaps and clarification answers in the relevant sections.
{PRD_STRUCTURE}
{ANALYSIS_RULES}

Respond with ONLY a single JSON object matching this schema, no prose, no markdown fences around \
the JSON itself (the markdown field's VALUE should of course contain markdown):"""


def _clarification_answers(store: CaseStore) -> str:
    workbook_path = store.artifact_path("validation_workbook.xlsx")
    workbook = load_workbook(workbook_path, data_only=False)
    if "Questions" not in workbook.sheetnames:
        return ""
    sheet = workbook["Questions"]
    # Columns: Report Table, Requirement ID, Question, Priority, Answer
    unanswered_questions = [
        f"{row[0] or 'General'}: {row[2]}"
        for row in sheet.iter_rows(min_row=2, values_only=True)
        if row[2] and not row[4]
    ]
    if unanswered_questions:
        raise ValueError(
            "Complete every answer in the 'Questions' worksheet before generating "
            "the PRD: " + "; ".join(unanswered_questions)
        )
    return "\n".join(
        f"- ({row[0] or 'General'}) Question: {row[2]} | Answer: {row[4]}"
        for row in sheet.iter_rows(min_row=2, values_only=True)
        if row[2]
    )


def run(
    store: CaseStore,
    claude: ClaudeClient,
    baseline: RequirementBaseline,
    decomposition: RequirementDecomposition,
    data_needs: DataNeedSpecification,
    validation: HumanValidationResult,
    gap_analysis: GapAnalysis,
) -> ScopeDocument:
    system_prompt = with_schema(INSTRUCTION, ScopeDocument)

    requirements_text = "\n".join(
        f"- {requirement.requirement_id} [{requirement.category}]: {requirement.description}; "
        f"evidence={requirement.evidence}; sources={requirement.source_systems}; "
        f"surfaces={requirement.report_surfaces}; acceptance={requirement.acceptance_criteria}; "
        f"validation={requirement.validation_method or 'not supplied'}"
        for requirement in decomposition.requirements
    )
    needs_text = "\n".join(
        f"- {need.requirement_id}: " + "; ".join(
            f"{concept.concept}; formula={concept.metric_formula or 'not supplied'}; "
            f"rulebook_ref={concept.rulebook_reference or 'not supplied'}"
            for concept in need.data_concepts
        )
        for need in data_needs.needs
    )
    validation_text = "\n".join(
        f"- {record.requirement_id} [{record.validation_status}]: {record.human_notes or ''}; "
        f"client answer={record.client_answer or ''}"
        for record in validation.records
    )
    clarifications_text = "\n".join(
        f"- ({', '.join(q.related_requirement_ids)}) {q.question}" for q in gap_analysis.clarification_questions
    )
    assessment_text = (
        gap_analysis.assessment.model_dump_json(indent=2)
        if gap_analysis.assessment
        else "No separate analytical assessment was persisted; use only the evidence below."
    )

    user_prompt = (
        f"BASELINE SUMMARY:\n{baseline.summary}\n\n"
        f"OBJECTIVES:\n{baseline.objectives}\n\n"
        f"IN SCOPE:\n{baseline.in_scope}\n\n"
        f"OUT OF SCOPE:\n{baseline.out_of_scope}\n\n"
        f"ASSUMPTIONS:\n{baseline.assumptions}\n\n"
        f"SOURCE-OF-TRUTH RULES:\n{baseline.source_of_truth_rules}\n\n"
        f"BASELINE REPORT DEFINITIONS:\n{[report.model_dump() for report in baseline.reports]}\n\n"
        f"BASELINE METRIC DEFINITIONS:\n{[metric.model_dump() for metric in baseline.metrics]}\n\n"
        f"COMMERCIAL TERMS:\n{baseline.commercial_terms}\n\n"
        f"DELIVERY COMMITMENTS:\n{baseline.delivery_commitments}\n\n"
        f"FINALIZED REQUIREMENTS:\n{requirements_text}\n\n"
        f"KNOWLEDGE-BASE DATA NEEDS:\n{needs_text}\n\n"
        f"HUMAN VALIDATION RESULTS:\n{validation_text}\n\n"
        "MISSING DATA:\n" + "\n".join(f"- {m}" for m in gap_analysis.missing_data) + "\n\n"
        "CONFLICTING DEFINITIONS:\n" + "\n".join(f"- {c}" for c in gap_analysis.conflicting_definitions) + "\n\n"
        f"CLARIFICATION QUESTIONS:\n{clarifications_text}\n\n"
        f"HUMAN / CLIENT CLARIFICATION ANSWERS:\n{_clarification_answers(store)}\n\n"
        f"OVERALL READINESS: {gap_analysis.overall_readiness}\n\n"
        f"INTERNAL ANALYTICAL ASSESSMENT (evidence and limitations must be preserved):\n{assessment_text}\n\n"
        f"ACCEPTANCE CRITERIA:\n{baseline.acceptance_criteria}\n\n"
        "Produce the PRD draft JSON now."
    )

    scope_doc = call_and_validate(
        claude, store, STAGE_NUM, system_prompt, user_prompt, ScopeDocument, max_tokens=8192
    )
    forbidden = ("[Editable", "Editable by human", "To be finalized", "Enter effort", "Enter rate")
    if any(token.lower() in scope_doc.markdown.lower() for token in forbidden):
        raise ValueError("Generated PRD contains an editable placeholder; generation must be evidence-complete.")
    scope_doc.markdown = normalize_prd_markdown(scope_doc.markdown)
    store.save_stage(STAGE_NUM, scope_doc)
    store.save_prd(scope_doc.markdown)
    render(scope_doc.markdown, store.artifact_path("client_ready_prd.docx"))
    render_pdf(scope_doc.markdown, store.artifact_path("client_ready_prd.pdf"))
    return scope_doc
