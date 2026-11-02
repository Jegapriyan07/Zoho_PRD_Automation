"""Stage 3: Transcript Analysis and Upfront Clarification.

Turns transcript evidence into an auditable business-analysis brief before
requirements are reconciled. It identifies ambiguity and asks answerable
questions; it does not expose private model reasoning or make client decisions.
"""
from pipeline.case_store import CaseStore
from pipeline.claude_client import ClaudeClient
from pipeline.json_utils import extract_json
from pipeline.models import CaseContext, TranscriptAnalysis
from pipeline.prompt_utils import with_schema
from pipeline.template_contract import ANALYSIS_RULES

STAGE_NUM = 3

INSTRUCTION = f"""You are a senior Zoho Analytics business-value analyst reviewing meeting evidence before implementation planning.
Produce an auditable analysis brief, not hidden chain-of-thought. Report only concise evidence-based conclusions, assumptions,
risks, and questions that a human stakeholder can answer.

Rules:
- Distinguish explicit stakeholder goals from analyst suggestions, examples, sales language, and unresolved discussion.
- Identify ambiguity in metric definitions, source-of-truth decisions, time periods, grain, filters, ownership, data quality,
  security, deliverables, and acceptance criteria when present.
- Explain the business impact of each ambiguity in terms of reporting correctness, decision usefulness, implementation effort,
  or Zoho Analytics feasibility.
- Ask one decision per question. Offer realistic options only when the transcript supports them; do not invent facts.
- Prioritize questions that could change the data model, formulas, source systems, scope, or acceptance decision as blocking.
- Do not silently resolve ambiguity. Do not claim a field, report, integration, or Zoho Analytics capability exists without evidence.
- Never include private chain-of-thought, token-by-token reasoning, or unsupported speculation.
- Populate evidence_items, business_objectives, source_systems, source_of_truth_rules, metric_definitions,
  report_requirements, commercial_terms, and delivery_commitments whenever the evidence supports them.
- For report_requirements, capture purpose, grain, columns/metrics, filters, business rules, source requirements,
  and acceptance criteria. Do not invent report names or fields.
{ANALYSIS_RULES}
- Respond with ONLY one JSON object matching the schema, with no markdown fences or prose outside JSON."""


def _format_sources(context: CaseContext) -> str:
    parts = [f"--- TRANSCRIPT {i}: {doc.filename} ---\n{doc.text}" for i, doc in enumerate(context.transcripts, 1)]
    if context.requirement_doc:
        parts.append(f"--- REQUIREMENT DOCUMENT: {context.requirement_doc.filename} ---\n{context.requirement_doc.text}")
    return "\n\n".join(parts)


def _render_report(analysis: TranscriptAnalysis) -> str:
    lines = ["# Transcript Analysis and Clarification Brief", "", f"**Readiness:** `{analysis.readiness}`", "", "## Executive Summary", analysis.executive_summary]
    for title, items in (
        ("Confirmed Signals", analysis.confirmed_signals),
        ("Assumptions to Validate", analysis.assumptions_to_validate),
        ("Ambiguity Risks", analysis.ambiguity_risks),
    ):
        lines.extend(["", f"## {title}"])
        lines.extend(f"- {item}" for item in items) or lines.append("- None identified.")
    lines.extend(["", "## Evidence Classification"])
    if analysis.evidence_items:
        for item in analysis.evidence_items:
            source = f" ({item.source})" if item.source else ""
            role = f"{item.speaker_or_role}: " if item.speaker_or_role else ""
            lines.append(
                f"- [{item.classification}; {item.evidence_strength}] {role}{item.statement}{source}"
            )
    else:
        lines.append("- No structured evidence items returned.")
    lines.extend(["", "## Clarification Questions"])
    if not analysis.clarification_questions:
        lines.append("No clarification questions identified.")
    for item in analysis.clarification_questions:
        lines.extend([
            "",
            f"### {item.question_id} [{item.priority}]",
            item.question,
            f"- Ambiguity: {item.ambiguity}",
            f"- Business impact: {item.business_impact}",
            f"- Related topics: {', '.join(item.related_topics) or 'None specified'}",
            f"- Automated answer: {item.answer}" if item.answer else "",
        ])
        if item.options:
            lines.append("- Options: " + "; ".join(item.options))
    for title, items in (
        ("Business Objectives", analysis.business_objectives),
        ("Source-of-Truth Rules", analysis.source_of_truth_rules),
        ("Commercial Terms", analysis.commercial_terms),
        ("Delivery Commitments", analysis.delivery_commitments),
    ):
        lines.extend(["", f"## {title}"])
        lines.extend(f"- {item}" for item in items) or lines.append("- None identified.")
    lines.extend(["", "_This brief records decisions needed from stakeholders; it is not a transcript of private model reasoning._", ""])
    return "\n".join(lines)


def run(store: CaseStore, claude: ClaudeClient, context: CaseContext) -> TranscriptAnalysis:
    system_prompt = with_schema(INSTRUCTION, TranscriptAnalysis)
    user_prompt = f"CASE ID: {context.case_id}\n\n{_format_sources(context)}\n\nProduce the analysis brief JSON now."
    response_text = claude.call(system_prompt, user_prompt)
    store.log_claude_call(STAGE_NUM, system_prompt, user_prompt, response_text)
    analysis = TranscriptAnalysis.model_validate(extract_json(response_text))
    store.save_stage(STAGE_NUM, analysis)
    store.save_transcript_analysis_report(_render_report(analysis))
    return analysis