"""Stage 3: Requirement Reconciliation.

Compares all provided transcripts (+ optional requirement doc) and produces
one consistent requirement baseline, flagging conflicts between sources.
"""
from pipeline.case_store import CaseStore
from pipeline.claude_client import ClaudeClient
from pipeline.json_utils import extract_json
from pipeline.models import CaseContext, RequirementBaseline, TranscriptAnalysis
from pipeline.prompt_utils import with_schema
from pipeline.template_contract import ANALYSIS_RULES

STAGE_NUM = 4

INSTRUCTION = f"""You are the senior requirements analyst for an analytics support team. Your output \
will become the foundation of a client-facing PRD and budget estimate. Read the complete meeting \
transcript(s) and optional requirement document as a connected conversation, not as a bag of sentences.

Rules:
- Separate the CLIENT'S business need from the analytics team's conversation. A client requirement \
is something the client wants the delivered report, dashboard, data flow, calculation, filter, \
business rule, support outcome, or deliverable to do.
- Do NOT turn analyst questions, confirmations, explanations of our process, trial-extension \
coordination, requests to share a screen, pricing explanations stated by our team, implementation \
estimates, or internal next steps into client functional requirements. Include commercial terms only \
when they are explicitly agreed as part of the requested engagement or PRD scope.
- Infer the client's complete intent from the surrounding turns. A client may describe one dashboard \
requirement across several turns; merge those turns into one coherent requirement instead of copying \
individual sentences.
- Preserve requirement bundles. For example, a P&L dashboard is one client requirement that may \
contain many metrics, dimensions, filters, data sources, and calculation rules. Do not split it into \
one baseline row per sentence or per metric.
- Include the business context, requested outcome, scope boundaries, source systems, dimensions, \
time logic, calculations, exclusions, and unresolved decisions needed to estimate the work.
- Where sources agree, state the agreed client requirement once in `baseline_requirements` as a \
complete multi-sentence requirement unit. Each item should be understandable without the transcript.
- Where sources disagree or are ambiguous (for example different revenue timing or metric definitions), \
record it as a conflict in `conflicts` rather than silently picking one. Explain what decision is needed.
- Use the meeting participants' roles and wording as evidence, but never assume that a statement from \
the analytics team is a client requirement merely because it contains words like "report", "fee", or "dashboard".
- Preserve the analysis brief's evidence classifications and carry confirmed objectives, scope boundaries,
  source precedence, metric definitions, report structures, acceptance criteria, commercial terms, and delivery
  commitments into the corresponding fields. Keep unresolved items in conflicts, assumptions, or acceptance criteria.
{ANALYSIS_RULES}
- Respond with ONLY a single JSON object matching this schema, no prose, no markdown fences:"""


def _format_sources(context: CaseContext) -> str:
    parts = []
    for i, t in enumerate(context.transcripts, start=1):
        parts.append(f"--- TRANSCRIPT {i}: {t.filename} ---\n{t.text}")
    if context.requirement_doc:
        parts.append(f"--- REQUIREMENT DOC: {context.requirement_doc.filename} ---\n{context.requirement_doc.text}")
    return "\n\n".join(parts)


def run(
    store: CaseStore,
    claude: ClaudeClient,
    context: CaseContext,
    transcript_analysis: TranscriptAnalysis | None = None,
) -> RequirementBaseline:
    system_prompt = with_schema(INSTRUCTION, RequirementBaseline)
    analysis_text = transcript_analysis.model_dump_json(indent=2) if transcript_analysis else "Not available."
    user_prompt = (
        f"CASE ID: {context.case_id}\n\nUPFRONT TRANSCRIPT ANALYSIS:\n{analysis_text}\n\n"
        f"{_format_sources(context)}\n\n"
        "Produce the requirement baseline JSON now."
    )

    response_text = claude.call(system_prompt, user_prompt)
    store.log_claude_call(STAGE_NUM, system_prompt, user_prompt, response_text)

    baseline = RequirementBaseline.model_validate(extract_json(response_text))
    store.save_stage(STAGE_NUM, baseline)
    return baseline
