"""Stage 3: Transcript Analysis and Upfront Clarification.

Turns transcript evidence into an auditable business-analysis brief before
requirements are reconciled. It identifies ambiguity and asks answerable
questions; it does not expose private model reasoning or make client decisions.
Large transcript collections are analyzed hierarchically: chunk evidence is
extracted first, then consolidated globally before the stage handoff.
"""
import os

from pipeline.case_store import CaseStore
from pipeline.claude_client import ClaudeClient
from pipeline.json_utils import extract_json
from pipeline.models import CaseContext, TranscriptAnalysis, TranscriptChunkAnalysis
from pipeline.prompt_utils import with_schema
from pipeline.template_contract import ANALYSIS_RULES

STAGE_NUM = 3

INSTRUCTION = f"""You are a senior Zoho Analytics business-value analyst reviewing meeting evidence before implementation planning.
Produce an auditable analysis brief, not hidden chain-of-thought. Report only concise evidence-based conclusions, assumptions,
risks, and questions that a human stakeholder can answer.

Rules:
- Treat all meetings as one connected customer discussion. Do not create a requirement for each
  statement, paragraph, or meeting. Consolidate related conversations into distinct business
  outcomes, preserving the supporting references from every meeting.
- Treat the original requirement document as the formal requirement source. Treat transcripts as
  context, clarification, correction, contradiction, or unresolved discussion; never promote a
  transcript suggestion over the document without recording the conflict.
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
- Before finalizing, check semantic duplication, fragmented requirements, chronological changes,
  contradictions, cross-meeting context, and whether each requirement represents a distinct
  business outcome.
{ANALYSIS_RULES}
- Respond with ONLY one JSON object matching the schema, with no markdown fences or prose outside JSON."""

CHUNK_INSTRUCTION = f"""You are extracting structured evidence from one bounded section of a customer
meeting transcript as part of a hierarchical enterprise business analysis.

This is an evidence pass, not the final requirement list. Capture concise, traceable evidence only.
Do not treat candidate requirements in this chunk as final requirements and do not infer missing
context. Classify statements as objectives, candidate requirements, analytical specifications,
business rules, clarifications, confirmations, changes, suggestions, assumptions, or unresolved
questions. Preserve the source filename and chunk reference in evidence. Never invent fields,
metrics, business decisions, or approvals.
{ANALYSIS_RULES}
- Respond with ONLY one JSON object matching the schema, with no markdown fences or prose outside JSON."""

DEFAULT_CHUNK_CHARS = 18000


def _chunk_transcript(filename: str, text: str, chunk_chars: int) -> list[tuple[str, str]]:
    if len(text) <= chunk_chars:
        return [(f"{filename}#chunk-001", text)]
    chunks = []
    start = 0
    number = 1
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n\n", start, end), text.rfind("\n", start, end))
            if boundary > start + chunk_chars // 2:
                end = boundary
        chunks.append((f"{filename}#chunk-{number:03d}", text[start:end].strip()))
        start = end
        number += 1
    return chunks


def _needs_hierarchical_analysis(context: CaseContext, chunk_chars: int) -> bool:
    transcript_chars = sum(len(doc.text) for doc in context.transcripts)
    return transcript_chars > chunk_chars


def _chunk_prompt(source: str, text: str) -> str:
    return f"SOURCE CHUNK: {source}\n\n{ text }\n\nExtract the bounded evidence JSON now."


def _format_sources(context: CaseContext) -> str:
    parts = [f"--- MEETING TRANSCRIPT {i} (CONTEXT ONLY): {doc.filename} ---\n{doc.text}" for i, doc in enumerate(context.transcripts, 1)]
    if context.requirement_doc:
        parts.append(
            f"--- ORIGINAL CUSTOMER REQUIREMENT DOCUMENT (AUTHORITATIVE): "
            f"{context.requirement_doc.filename} ---\n{context.requirement_doc.text}"
        )
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
    chunk_chars = int(os.getenv("TRANSCRIPT_ANALYSIS_CHUNK_CHARS", str(DEFAULT_CHUNK_CHARS)))
    if chunk_chars < 1000:
        raise ValueError("TRANSCRIPT_ANALYSIS_CHUNK_CHARS must be at least 1000.")

    if not _needs_hierarchical_analysis(context, chunk_chars):
        system_prompt = with_schema(INSTRUCTION, TranscriptAnalysis)
        user_prompt = f"CASE ID: {context.case_id}\n\n{_format_sources(context)}\n\nProduce the analysis brief JSON now."
        response_text = claude.call(system_prompt, user_prompt)
        store.log_claude_call(STAGE_NUM, system_prompt, user_prompt, response_text)
        analysis = TranscriptAnalysis.model_validate(extract_json(response_text))
    else:
        chunk_analyses = []
        chunk_system_prompt = with_schema(CHUNK_INSTRUCTION, TranscriptChunkAnalysis)
        for document in context.transcripts:
            for source, text in _chunk_transcript(document.filename, document.text, chunk_chars):
                user_prompt = _chunk_prompt(source, text)
                response_text = claude.call(chunk_system_prompt, user_prompt)
                store.log_claude_call(STAGE_NUM, chunk_system_prompt, user_prompt, response_text, source.replace("#", "_"))
                chunk_analyses.append(TranscriptChunkAnalysis.model_validate(extract_json(response_text)))

        consolidation_system_prompt = with_schema(INSTRUCTION, TranscriptAnalysis)
        evidence_text = "\n\n".join(
            f"--- CHUNK EVIDENCE: {chunk.chunk_reference} ---\n{chunk.model_dump_json(indent=2)}"
            for chunk in chunk_analyses
        )
        requirement_text = (
            f"\n\n--- ORIGINAL CUSTOMER REQUIREMENT DOCUMENT (AUTHORITATIVE): "
            f"{context.requirement_doc.filename} ---\n{context.requirement_doc.text}"
            if context.requirement_doc else ""
        )
        consolidation_user_prompt = (
            f"CASE ID: {context.case_id}\n\n"
            "The following are chunk-level evidence extracts from all meetings. They are not a final "
            "requirement list. Consolidate them globally, deduplicate semantically, connect fragmented "
            "details, preserve chronological changes and contradictions, and ensure each final report "
            "requirement represents a distinct business outcome.\n\n"
            f"{evidence_text}{requirement_text}\n\n"
            "Produce the globally consolidated analysis brief JSON now."
        )
        response_text = claude.call(
            consolidation_system_prompt, consolidation_user_prompt, max_tokens=8192
        )
        store.log_claude_call(
            STAGE_NUM, consolidation_system_prompt, consolidation_user_prompt, response_text, "consolidation"
        )
        analysis = TranscriptAnalysis.model_validate(extract_json(response_text))
        analysis.chunk_analyses = chunk_analyses

    store.save_stage(STAGE_NUM, analysis)
    store.save_transcript_analysis_report(_render_report(analysis))
    return analysis