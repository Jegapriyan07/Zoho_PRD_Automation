"""Stage 10: generate a complete PRD from finalized evidence and validation."""
from openpyxl import load_workbook

from pipeline.case_store import CaseStore
from pipeline.claude_client import ClaudeClient
from pipeline.json_utils import extract_json
from pipeline.models import (
    DataNeedSpecification,
    GapAnalysis,
    HumanValidationResult,
    RequirementBaseline,
    RequirementDecomposition,
    ScopeDocument,
)
from pipeline.prd_docx_renderer import render, render_pdf
from pipeline.prompt_utils import with_schema
from pipeline.template_contract import PRD_STRUCTURE, ANALYSIS_RULES

STAGE_NUM = 11

INSTRUCTION = f"""You generate a complete, client-ready Project Requirements Document as Markdown, built from the finalized \
requirements, the validation workbook, rulebook-grounded data needs, and evidence-backed gap analysis. \
The baseline and requirements are transcript-derived; do not omit a material business rule, source, filter, \
formula, commercial term, delivery step, support commitment, or unresolved decision that appears in them.

The document MUST use exactly these top-level sections, in this order, as Markdown "##" headings:

## Document Overview
## The Challenge
## Data Sources
## Our Approach / How It Works
## Data Preparation
## Detailed Requirements
## The Workflow
## Estimated Effort
## Project Cost
## The Outcome

Guidance per section:
- Begin with one H1 title that names the solution and client where known, followed by a one-line subtitle.
- Document Overview must include Purpose, What this document covers, and Intended audience.
- Data Sources must identify every source, its relevant tables/files, fields, ownership, and intended use.
- Our Approach / How It Works must explain the consolidated reporting layer, source precedence, and human review.
- Data Preparation must cover integration, consolidation/blending, account grouping/remapping, tags, and calculated metrics.
- Detailed Requirements must contain three named subsections and one Markdown table for each: Property-Level Custom P&L, \
    Portfolio / All-Properties Comparison, and Current Assets Summary. Each table must include Report Name, Columns, \
    Filters, and Report Explanation, using the exact fields and filters from the validated workbook wherever available.
- The Workflow must use numbered steps with owner labels and effort labels. Include customer preparation, consolidation, \
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
    sheet = workbook["Gaps & Clarifications"]
    unanswered_questions = [
        f"{row[0] or 'general'}: {row[1]}"
        for row in sheet.iter_rows(min_row=2, values_only=True)
        if row[1] and not row[2]
    ]
    if unanswered_questions:
        raise ValueError(
            "Complete every answer in the 'Gaps & Clarifications' worksheet before generating "
            "the PRD: " + "; ".join(unanswered_questions)
        )
    answers = [
        f"- ({row[0] or 'general'}) Question: {row[1]} | Answer: {row[2]}"
        for row in sheet.iter_rows(min_row=2, values_only=True)
        if row[1]
    ]
    questions = workbook["Questions"] if "Questions" in workbook.sheetnames else None
    if questions:
        unanswered_questions = [
            f"{row[0]}: {row[1]}"
            for row in questions.iter_rows(min_row=2, values_only=True)
            if row[1] and not row[3]
        ]
        if unanswered_questions:
            raise ValueError(
                "Complete every answer in the 'Questions' worksheet before generating "
                "the PRD: " + "; ".join(unanswered_questions)
            )
        answers.extend(
            f"- ({row[0]}) Question: {row[1]} | Answer: {row[3]}"
            for row in questions.iter_rows(min_row=2, values_only=True)
            if row[1]
        )
    return "\n".join(answers)


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

    response_text = claude.call(system_prompt, user_prompt, max_tokens=8192)
    store.log_claude_call(STAGE_NUM, system_prompt, user_prompt, response_text)

    scope_doc = ScopeDocument.model_validate(extract_json(response_text))
    forbidden = ("[Editable", "Editable by human", "To be finalized", "Enter effort", "Enter rate")
    if any(token.lower() in scope_doc.markdown.lower() for token in forbidden):
        raise ValueError("Generated PRD contains an editable placeholder; generation must be evidence-complete.")
    store.save_stage(STAGE_NUM, scope_doc)
    store.save_prd(scope_doc.markdown)
    render(scope_doc.markdown, store.artifact_path("client_ready_prd.docx"))
    render_pdf(scope_doc.markdown, store.artifact_path("client_ready_prd.pdf"))
    return scope_doc
