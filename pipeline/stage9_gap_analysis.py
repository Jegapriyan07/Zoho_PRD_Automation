"""Stage 9: Gap & Clarification Analysis from human Excel validation."""
from pipeline.case_store import CaseStore
from pipeline.claude_client import ClaudeClient
from pipeline.json_utils import extract_json
from pipeline.models import DataNeedSpecification, GapAnalysis, HumanValidationResult, RequirementDecomposition
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
- Set overall_readiness to READY only if every human-validated record is Available; PARTIALLY READY \
if there is a mix but most are resolvable; BLOCKED if missing items block core objectives.
- Respond with ONLY a single JSON object matching this schema, no prose, no markdown fences:"""


def run(
    store: CaseStore,
    claude: ClaudeClient,
    validation: HumanValidationResult,
    decomposition: RequirementDecomposition,
    data_needs: DataNeedSpecification,
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
    user_prompt = (
        f"FINALIZED REQUIREMENTS:\n{requirements_text}\n\n"
        f"REQUIRED METRICS AND DATA CONCEPTS:\n{metrics_text}\n\n"
        f"HUMAN VALIDATION RESULTS:\n{validation_text}\n\n"
        "Produce the gap analysis JSON now."
    )

    response_text = claude.call(system_prompt, user_prompt)
    store.log_claude_call(STAGE_NUM, system_prompt, user_prompt, response_text)

    gap_analysis = GapAnalysis.model_validate(extract_json(response_text))
    store.save_stage(STAGE_NUM, gap_analysis)
    return gap_analysis
