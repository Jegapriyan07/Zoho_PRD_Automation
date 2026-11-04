"""Stage 9: Gap & Clarification Analysis from human Excel validation."""
from pipeline.case_store import CaseStore
from pipeline.claude_client import ClaudeClient
from pipeline.json_utils import extract_json
from pipeline.models import (
    AnalyticalAssessment,
    DataNeedSpecification,
    EvidenceReference,
    GapAnalysis,
    HumanValidationResult,
    MetadataMapping,
    RequirementBaseline,
    RequirementDecomposition,
    SQLDiscovery,
    TranscriptAnalysis,
)
from pipeline.prompt_utils import with_schema

STAGE_NUM = 10

INSTRUCTION = """You review a completed requirement-to-data mapping table and identify genuine \
gaps, conflicting definitions, and produce specific clarification questions for the client.

Rules:
- Use the human's workbook status as the authority. List missing_data for Missing, Soiled Data, \
Partially Available, or Unclear records, summarizing the issue and referencing requirement_ids.
- Review the finalized requirements and required metrics too. List conflicting_definitions for any \
requirement weakness or definitional ambiguity (e.g. two plausible interpretations of a metric).
- Write clarification_questions as specific, answerable questions a client stakeholder could \
respond to directly, referencing related_requirement_ids.
- Classify gaps beyond missing fields: business definition, formula, source field, relationship,
  granularity, history, filters/dimensions, technical feasibility, validation, and clarification.
- For each mapping or feasibility conclusion, distinguish schema support from actual data
  population, completeness, accuracy, and historical coverage. Metadata-only evidence cannot prove
  those data properties.
- Populate assessment with an executive summary, requirement inventory, metric feasibility,
  metadata mappings, evidence references, limitations, gaps, quality checks, and readiness.
- Use UNVERIFIED whenever the available evidence cannot establish a conclusion. Never invent
  customer-specific tables, columns, formulas, or relationships.
- Set overall_readiness to READY only if every human-validated record is Available; PARTIALLY READY \
if there is a mix but most are resolvable; BLOCKED if missing items block core objectives.
- Respond with ONLY a single JSON object matching this schema, no prose, no markdown fences:"""


def run(
    store: CaseStore,
    claude: ClaudeClient,
    validation: HumanValidationResult,
    decomposition: RequirementDecomposition,
    data_needs: DataNeedSpecification,
    sql_discovery: SQLDiscovery | None = None,
    baseline: RequirementBaseline | None = None,
    transcript_analysis: TranscriptAnalysis | None = None,
) -> GapAnalysis:
    system_prompt = with_schema(INSTRUCTION, GapAnalysis)

    validation_text = "\n".join(
        f"- {record.requirement_id} [{record.validation_status}]: notes={record.human_notes or ''} "
        f"client_answer={record.client_answer or ''}"
        for record in validation.records
    )
    requirements_text = "\n".join(
        f"- {requirement.requirement_id}: {requirement.description}"
        for requirement in decomposition.requirements
    )
    metrics_text = "\n".join(
        f"- {need.requirement_id}: " + "; ".join(
            f"{concept.concept} (formula: {concept.metric_formula or 'not found'})"
            for concept in need.data_concepts
        )
        for need in data_needs.needs
    )
    metadata_text = "\n".join(
        f"- {query.requirement_id}: status={query.mapping_status}; paths={query.metadata_paths}; "
        f"validation={query.validation_status}; rationale={query.mapping_rationale}; "
        f"missing={query.missing_dependencies}"
        for query in (sql_discovery.queries if sql_discovery else [])
    ) or "Workspace metadata mapping was not supplied."
    source_text = (
        f"AUTHORITATIVE REQUIREMENT DOCUMENT BASELINE:\n"
        f"summary={baseline.summary}\nrequirements={baseline.baseline_requirements}\n"
        f"objectives={baseline.objectives}\nconflicts={baseline.conflicts}\n"
        if baseline else "Authoritative requirement baseline was not supplied."
    )
    transcript_text = (
        transcript_analysis.model_dump_json(indent=2)
        if transcript_analysis else "Transcript analysis was not supplied."
    )
    user_prompt = (
        f"{source_text}\n\nTRANSCRIPT RECONCILIATION BRIEF:\n{transcript_text}\n\n"
        f"FINALIZED REQUIREMENTS:\n{requirements_text}\n\n"
        f"REQUIRED METRICS AND DATA CONCEPTS:\n{metrics_text}\n\n"
        f"WORKSPACE METADATA MAPPINGS:\n{metadata_text}\n\n"
        f"HUMAN VALIDATION RESULTS:\n{validation_text}\n\n"
        "Produce the gap analysis JSON now."
    )

    response_text = claude.call(system_prompt, user_prompt)
    store.log_claude_call(STAGE_NUM, system_prompt, user_prompt, response_text)

    gap_analysis = GapAnalysis.model_validate(extract_json(response_text))
    store.save_stage(STAGE_NUM, gap_analysis)
    derived_mappings = [
        MetadataMapping(
            requirement_id=query.requirement_id,
            business_concept=query.purpose,
            entity=(query.metadata_paths[0].split(".")[0] if query.metadata_paths else None),
            column=(query.metadata_paths[0].split(".")[-1] if query.metadata_paths else None),
            mapping_status=query.mapping_status,
            rationale=query.mapping_rationale,
            missing_dependencies=query.missing_dependencies,
            validation_status=query.validation_status,
            evidence=[EvidenceReference(
                source_type="ZOHO_METADATA",
                reference=path,
                statement="Metadata path supplied by the workspace mapping stage.",
                status="SUPPORTED",
            ) for path in query.metadata_paths],
        )
        for query in (sql_discovery.queries if sql_discovery else [])
    ]
    assessment = gap_analysis.assessment or AnalyticalAssessment(
        executive_summary=(
            "The internal assessment is based on the finalized requirements, rulebook evidence, "
            "workspace metadata mapping, and human validation results. Unverified conclusions "
            "remain explicitly unverified."
        ),
        readiness=gap_analysis.overall_readiness,
        requirement_inventory=[
            f"{item.requirement_id}: {item.description}" for item in decomposition.requirements
        ],
        confirmed_objectives=baseline.objectives if baseline else [],
        transcript_reconciliation=(
            transcript_analysis.confirmed_signals if transcript_analysis else []
        ),
        gaps=gap_analysis.gaps,
        metadata_mappings=derived_mappings,
        clarification_questions=gap_analysis.clarification_questions,
        technical_limitations=[
            "Metadata-only discovery cannot establish record completeness, value accuracy, or historical coverage."
        ],
        quality_checks=[
            "Formal requirements were compared with the finalized decomposition.",
            "Workspace claims are limited to supplied metadata and human validation.",
            "Unknowns remain UNVERIFIED rather than being promoted to confirmed facts.",
        ],
    )
    if not assessment.metadata_mappings and derived_mappings:
        assessment.metadata_mappings = derived_mappings
    if not assessment.gaps and gap_analysis.gaps:
        assessment.gaps = gap_analysis.gaps
    gap_analysis.assessment = assessment
    store.save_stage(STAGE_NUM, gap_analysis)
    store.save_analytical_assessment(assessment, _render_assessment(assessment))
    return gap_analysis


def _render_assessment(assessment: AnalyticalAssessment) -> str:
    lines = [
        "# Internal Analytical Assessment",
        "",
        f"**Readiness:** `{assessment.readiness}`",
        "",
        "## Executive Summary",
        assessment.executive_summary or "No summary was returned.",
    ]
    sections = [
        ("Requirement Inventory", assessment.requirement_inventory),
        ("Confirmed Objectives", assessment.confirmed_objectives),
        ("Transcript Reconciliation", assessment.transcript_reconciliation),
        ("Unresolved Assumptions", assessment.unresolved_assumptions),
        ("Contradictions", assessment.contradictions),
        ("Technical Limitations", assessment.technical_limitations),
        ("Implementation Considerations", assessment.implementation_considerations),
        ("Quality Checks", assessment.quality_checks),
    ]
    for title, items in sections:
        lines.extend(["", f"## {title}"])
        lines.extend(f"- {item}" for item in items) or lines.append("- None identified.")
    lines.extend(["", "## Metric and Feasibility Analysis"])
    if assessment.metric_analyses:
        for metric in assessment.metric_analyses:
            lines.extend([
                "",
                f"### {metric.requirement_id}: {metric.metric_name}",
                f"- Definition: {metric.business_definition or 'Unverified'}",
                f"- Formula: {metric.formula or 'Unverified'}",
                f"- Feasibility: `{metric.feasibility}`",
                f"- Dependencies: {', '.join(metric.dependencies) or 'None recorded'}",
            ])
    else:
        lines.append("- No metric analysis was returned.")
    lines.extend(["", "## Metadata Mappings"])
    if assessment.metadata_mappings:
        for mapping in assessment.metadata_mappings:
            location = f"{mapping.entity}.{mapping.column}" if mapping.entity and mapping.column else "No verified location"
            lines.append(
                f"- {mapping.requirement_id}: {mapping.business_concept} -> {location} "
                f"(`{mapping.mapping_status}`; {mapping.validation_status}) - {mapping.rationale}"
            )
    else:
        lines.append("- No metadata mappings were verified.")
    lines.extend(["", "## Gap Register"])
    if assessment.gaps:
        for gap in assessment.gaps:
            lines.append(
                f"- **{gap.gap_id} [{gap.severity}]** {gap.category}: {gap.description} "
                f"Action: {gap.recommended_action or 'Not specified'}"
            )
    else:
        lines.append("- No gaps returned.")
    lines.extend(["", "## Clarification Questions"])
    lines.extend(f"- {question.question}" for question in assessment.clarification_questions)
    if not assessment.clarification_questions:
        lines.append("- None identified.")
    return "\n".join(lines) + "\n"
