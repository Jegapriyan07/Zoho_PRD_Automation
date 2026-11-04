"""Deterministic, offline stand-in for ClaudeClient - no API key or network needed.

Uses simple keyword/regex heuristics (NOT real reasoning) so the full CLI pipeline
can be exercised end-to-end for local plumbing/testing. Output quality is
intentionally rough - swap back to the real ClaudeClient (drop --mock) once an
ANTHROPIC_API_KEY is available for production-quality reasoning.

Dispatch works by reading the Pydantic JSON schema that `prompt_utils.with_schema`
appends to every system prompt and looking at its "title" (the model class name),
so this client doesn't need to know which pipeline stage is calling it.
"""
import json
import re

# Every ALL-CAPS section header used across the stage prompts, used to bound
# a section's text when extracting it from a user prompt.
_SECTION_HEADERS = [
    "BASELINE SUMMARY:",
    "BASELINE REQUIREMENTS:",
    "ATOMIC REQUIREMENTS:",
    "DATA NEEDS:",
    "SQL EVIDENCE:",
    "REQUIREMENT-TO-DATA MAPPING:",
    "MISSING DATA:",
    "CONFLICTING DEFINITIONS:",
    "CLARIFICATION QUESTIONS:",
    "OVERALL READINESS:",
]

_STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "or", "to", "by", "in", "on", "with",
    "is", "are", "per", "each", "any", "be", "as", "at", "if", "it", "this",
}

_REQ_CATEGORY_LINE_RE = re.compile(r"^-\s*(REQ-\d+)\s*\[(\w+)\]:\s*(.+)$")
_REQ_PLAIN_LINE_RE = re.compile(r"^-\s*(REQ-\d+):\s*(.+)$")


def _extract_section(text: str, header: str) -> str:
    start = text.find(header)
    if start == -1:
        return ""
    start += len(header)
    end = len(text)
    for other in _SECTION_HEADERS:
        if other == header:
            continue
        pos = text.find(other, start)
        if pos != -1 and pos < end:
            end = pos
    return text[start:end].strip()


def _keywords(text: str) -> set:
    words = re.findall(r"[a-zA-Z_]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _guess_category(text: str) -> str:
    low = text.lower()
    if any(k in low for k in ("revenue", "profit", "margin", "count", "total", "amount", "time")):
        return "metric"
    if any(k in low for k in ("region", "segment", "category", "product line", "by ")):
        return "dimension"
    if any(k in low for k in ("filter", "only", "exclude", "flag", "past due", "breach")):
        return "filter"
    if any(k in low for k in ("year", "month", "period", "date", "window", "due")):
        return "time_logic"
    return "business_rule"


def _extract_trailing_schema(system_prompt: str) -> dict:
    idx = system_prompt.find("{")
    if idx == -1:
        return {}
    try:
        return json.loads(system_prompt[idx:])
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Stage 3: Transcript Analysis
# ---------------------------------------------------------------------------

def _transcript_analysis_handler(system_prompt: str, user_prompt: str) -> dict:
    has_multiple_sources = (
        user_prompt.count("--- TRANSCRIPT") > 1
        or user_prompt.count("--- MEETING TRANSCRIPT") > 1
        or "REQUIREMENT DOCUMENT" in user_prompt
    )
    questions = [{
        "question_id": "Q-001",
        "question": "Which stakeholder-approved definition and source should be authoritative when two sources report the same business measure differently?",
        "ambiguity": "The transcript may contain multiple candidate sources or definitions for the same measure.",
        "business_impact": "An unresolved choice can produce inconsistent dashboards and rework in the data model.",
        "options": ["Primary source with fallback", "Combine sources with a documented rule", "Defer the measure"],
        "priority": "blocking",
        "related_topics": ["source of truth", "metric definition"],
        "answer": None,
    }]
    if not has_multiple_sources:
        questions[0]["question"] = "What exact business decision should this analytics output support, and how will stakeholders decide that it is correct?"
        questions[0]["ambiguity"] = "The desired outcome or acceptance test is not explicit in the transcript evidence."
        questions[0]["business_impact"] = "Without an agreed outcome, the team may build a technically valid report that does not answer the business question."
        questions[0]["options"] = []
    return {
        "executive_summary": "[MOCK] Transcript evidence was reviewed for business intent, assumptions, and decisions that could affect analytics scope.",
        "confirmed_signals": ["The transcript is the source evidence for the initial business analysis."],
        "assumptions_to_validate": ["Stakeholders will answer blocking questions before implementation scope is finalized."],
        "ambiguity_risks": ["Metric definitions and source-of-truth decisions may change the required data model."],
        "clarification_questions": questions,
        "readiness": "needs_clarification",
        "evidence_items": [{
            "source": "mock input",
            "statement": "The transcript is the source evidence for the initial business analysis.",
            "classification": "client_need",
            "speaker_or_role": None,
            "evidence_strength": "explicit",
        }],
        "business_objectives": ["Produce an analytics output that stakeholders can validate against the stated business need."],
        "source_systems": ["Sources explicitly named in the transcript"],
        "source_of_truth_rules": [],
        "metric_definitions": [],
        "report_requirements": [],
        "commercial_terms": [],
        "delivery_commitments": [],
    }


def _transcript_chunk_analysis_handler(system_prompt: str, user_prompt: str) -> dict:
    source_match = re.search(r"SOURCE CHUNK:\s*(.+)", user_prompt)
    source = source_match.group(1).strip() if source_match else "unknown transcript chunk"
    text = user_prompt.split("\n\n", 1)[-1].strip()
    candidate_lines = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if 15 <= len(sentence.strip()) <= 300
        and any(keyword in sentence.lower() for keyword in _REQUIREMENT_KEYWORDS)
    ]
    return {
        "source": source.split("#", 1)[0],
        "chunk_reference": source,
        "executive_summary": "[MOCK] Bounded evidence extracted without treating it as final scope.",
        "business_objectives": [],
        "evidence_items": [],
        "candidate_topics": [],
        "candidate_requirements": candidate_lines[:20],
        "clarifications": [],
        "confirmations": [],
        "changes": [],
        "suggestions": [],
        "assumptions": [],
        "unresolved_questions": [],
        "metrics": [],
        "reports": [],
    }


# ---------------------------------------------------------------------------
# Stage 4: Requirement Reconciliation
# ---------------------------------------------------------------------------

_REQUIREMENT_KEYWORDS = (
    "want", "need", "track", "flag", "report", "dashboard", "breakdown",
    "segment", "measure", "should", "must", "require", "visibility", "count",
    "confirm", "show",
)


def _reconciliation_handler(system_prompt: str, user_prompt: str) -> dict:
    sentences = re.split(r"(?<=[.!?])\s+", user_prompt)
    seen, reqs = set(), []
    for s in sentences:
        s_clean = s.strip().strip('"')
        if not (15 <= len(s_clean) <= 300):
            continue
        if any(k in s_clean.lower() for k in _REQUIREMENT_KEYWORDS) and s_clean not in seen:
            seen.add(s_clean)
            reqs.append(s_clean)
    if not reqs:
        reqs = ["[MOCK] No explicit requirement sentences detected by local heuristic."]

    conflicts = []
    low = user_prompt.lower()
    if "12 months" in low and "calendar year" in low:
        conflicts.append({
            "topic": "Reporting time window",
            "description": "One source references a rolling 12-month window while another specifies a calendar year.",
            "sources": ["[MOCK] detected via keyword co-occurrence"],
        })

    summary = (
        f"[MOCK] Reconciled {len(reqs)} candidate requirement statement(s) from the provided "
        "sources via a local keyword heuristic (no live Claude call was made)."
    )
    return {
        "summary": summary,
        "baseline_requirements": reqs[:20],
        "conflicts": conflicts,
        "objectives": ["Deliver a validated analytics output grounded in the supplied evidence."],
        "in_scope": reqs[:20],
        "out_of_scope": [],
        "assumptions": ["Unresolved decisions remain visible until confirmed."],
        "source_of_truth_rules": [],
        "metrics": [],
        "reports": [],
        "acceptance_criteria": ["Every finalized requirement is traceable to source evidence and validation."],
        "commercial_terms": [],
        "delivery_commitments": [],
    }


# ---------------------------------------------------------------------------
# Stage 4: Requirement Decomposition
# ---------------------------------------------------------------------------

def _decomposition_handler(system_prompt: str, user_prompt: str) -> dict:
    section = _extract_section(user_prompt, "BASELINE REQUIREMENTS:")
    lines = [l.strip()[2:].strip() for l in section.splitlines() if l.strip().startswith("- ")]

    reqs = [
        {
            "requirement_id": f"REQ-{i:03d}",
            "category": _guess_category(desc),
            "description": desc,
            "source_reference": None,
            "evidence": ["Baseline requirement text"],
            "source_systems": [],
            "report_surfaces": [],
            "acceptance_criteria": [f"{desc} is demonstrable in the delivered scope."],
            "validation_method": "Review against source evidence and validation workbook.",
            "dependencies": [],
        }
        for i, desc in enumerate(lines, start=1)
    ]
    if not reqs:
        reqs = [{
            "requirement_id": "REQ-001",
            "category": "business_rule",
            "description": "[MOCK] No baseline requirements were parsed; check stage 3 output.",
            "source_reference": None,
            "evidence": ["Baseline requirement text"],
            "source_systems": [],
            "report_surfaces": [],
            "acceptance_criteria": ["The requirement is demonstrable in the delivered scope."],
            "validation_method": "Review against source evidence and validation workbook.",
            "dependencies": [],
        }]
    return {"requirements": reqs}


# ---------------------------------------------------------------------------
# Stage 5: Data Need Specification
# ---------------------------------------------------------------------------

_CATEGORY_TO_CONCEPT_TYPE = {
    "metric": "aggregation", "dimension": "field", "filter": "filter_value",
    "time_logic": "field", "business_rule": "entity",
}


def _data_needs_handler(system_prompt: str, user_prompt: str) -> dict:
    section = _extract_section(user_prompt, "ATOMIC REQUIREMENTS:")
    needs = []
    for line in section.splitlines():
        m = _REQ_CATEGORY_LINE_RE.match(line.strip())
        if not m:
            continue
        req_id, category, desc = m.groups()
        needs.append({
            "requirement_id": req_id,
            "data_concepts": [{
                "concept": desc,
                "concept_type": _CATEGORY_TO_CONCEPT_TYPE.get(category, "entity"),
                "notes": "[MOCK] concept text mirrors the requirement description; no real decomposition performed.",
            }],
        })
    return {"needs": needs}


# ---------------------------------------------------------------------------
# Stage 6: SQL Data Discovery
# ---------------------------------------------------------------------------

# Business-vocabulary guesses that mimic what a real LLM might try even without
# confirming column existence - this is what lets the mock reproduce the
# seeded gap (cancellation reason) and derivable (profit) scenarios realistically.
_GUESS_PATTERNS = [
    (("cancel", "reason"), "SELECT cancellation_reason FROM sales_orders LIMIT 5"),
    (("profit",), (
        "SELECT s.order_id, SUM((oi.unit_price - p.unit_cost) * oi.quantity) AS derived_profit "
        "FROM order_items oi JOIN sales_orders s ON s.order_id = oi.order_id "
        "JOIN products p ON p.product_id = oi.product_id GROUP BY s.order_id LIMIT 5"
    )),
    (("margin",), (
        "SELECT s.order_id, SUM((oi.unit_price - p.unit_cost) * oi.quantity) AS derived_profit "
        "FROM order_items oi JOIN sales_orders s ON s.order_id = oi.order_id "
        "JOIN products p ON p.product_id = oi.product_id GROUP BY s.order_id LIMIT 5"
    )),
    (("past", "due"), "SELECT invoice_id, due_date, status FROM invoices WHERE status != 'Paid' LIMIT 5"),
    (("payment", "method"), "SELECT payment_method, COUNT(*) AS cnt FROM payments GROUP BY payment_method LIMIT 5"),
    (("active", "product"), "SELECT is_active, COUNT(*) AS cnt FROM products GROUP BY is_active LIMIT 5"),
    (("sla",), "SELECT ticket_id, created_date, status FROM tickets LIMIT 5"),
    (("resolution",), "SELECT ticket_id, status, changed_date FROM ticket_status_history LIMIT 5"),
]


def _parse_db_schema(system_prompt: str) -> dict:
    m = re.search(r"DATABASE SCHEMA:\n(.*?)\n\nRules:", system_prompt, re.DOTALL)
    schema = {}
    if not m:
        return schema
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        table_part, _, cols_part = line[2:].partition(":")
        cols = [c.split("(")[0].strip() for c in cols_part.split(",") if c.strip()]
        schema[table_part.strip()] = cols
    return schema


def _best_table(concept_kw: set, schema: dict) -> tuple:
    best_table, best_cols, best_score = None, [], -1
    for table, cols in schema.items():
        table_kw = _keywords(table)
        matched_cols, col_kw = [], set()
        for c in cols:
            ckw = _keywords(c)
            col_kw |= ckw
            if ckw & concept_kw:
                matched_cols.append(c)
        score = len((table_kw | col_kw) & concept_kw) + len(matched_cols)
        if score > best_score:
            best_table, best_cols, best_score = table, matched_cols, score
    return best_table, best_cols


def _sql_discovery_handler(system_prompt: str, user_prompt: str) -> dict:
    schema = _parse_db_schema(system_prompt)
    tables = list(schema.keys())
    section = _extract_section(user_prompt, "DATA NEEDS:")

    queries = []
    for line in section.splitlines():
        m = _REQ_PLAIN_LINE_RE.match(line.strip())
        if not m:
            continue
        req_id, concepts_text = m.groups()
        for item in [c.strip() for c in concepts_text.split(";") if c.strip()]:
            item_low = item.lower()
            concept_kw = _keywords(item)
            table, matched_cols = _best_table(concept_kw, schema)
            if table is None and tables:
                table = tables[0]
            if table is None:
                continue
            select_cols = ", ".join(matched_cols) if matched_cols else "*"
            queries.append({
                "requirement_id": req_id,
                "purpose": f"[MOCK] best-effort keyword match for concept: {item}",
                "sql": f"SELECT {select_cols} FROM {table} LIMIT 5",
                "metadata_paths": [f"{table}.{column}" for column in matched_cols] or [table],
            })
    return {"queries": queries}


# ---------------------------------------------------------------------------
# Stage 9: Gap & Clarification Analysis
# ---------------------------------------------------------------------------

_MAPPING_LINE_RE = re.compile(r"^-\s*(REQ-\d+)\s*\[(\w+)\]:\s*(.+)$")


def _gap_analysis_handler(system_prompt: str, user_prompt: str) -> dict:
    section = _extract_section(user_prompt, "HUMAN VALIDATION RESULTS:")
    missing, clarifications, statuses = [], [], []

    for line in section.splitlines():
        m = re.match(r"^-\s*(REQ-\d+)\s*\[([^]]+)\]:\s*(.+)$", line.strip())
        if not m:
            continue
        req_id, status, rest = m.groups()
        normalized_status = status.strip().upper()
        statuses.append(normalized_status)
        if normalized_status in ("MISSING", "SOILED DATA", "PARTIALLY AVAILABLE", "UNCLEAR"):
            missing.append(f"{req_id}: human validation status is {status} ({rest[:160]})")
            clarifications.append({
                "topic": f"{req_id} validation follow-up",
                "question": f"Can you clarify or resolve the human validation issue for {req_id}?",
                "related_requirement_ids": [req_id],
            })

    if not statuses:
        overall = "BLOCKED"
    elif all(s == "Available" for s in statuses):
        overall = "READY"
    elif statuses.count("MISSING") > len(statuses) // 2:
        overall = "BLOCKED"
    else:
        overall = "PARTIALLY READY"

    return {
        "missing_data": missing,
        "conflicting_definitions": [],
        "clarification_questions": clarifications,
        "overall_readiness": overall,
    }


# ---------------------------------------------------------------------------
# Stage 10: Scope Generation
# ---------------------------------------------------------------------------

def _scope_generation_handler(system_prompt: str, user_prompt: str) -> dict:
    baseline_summary = _extract_section(user_prompt, "BASELINE SUMMARY:")
    mapping_section = _extract_section(user_prompt, "FINALIZED REQUIREMENTS:")
    clarifications_section = _extract_section(user_prompt, "CLARIFICATION QUESTIONS:")
    readiness_m = re.search(r"OVERALL READINESS:\s*(.+)", user_prompt)
    readiness = readiness_m.group(1).strip() if readiness_m else "PARTIALLY READY"

    mapping_rows = [
        m.groups() for m in (_MAPPING_LINE_RE.match(l.strip()) for l in mapping_section.splitlines()) if m
    ]
    availability_table = "| Requirement | Status | Rationale |\n|---|---|---|\n" + "\n".join(
        f"| {req_id} | {status} | {rest[:140]} |" for req_id, status, rest in mapping_rows
    )
    in_scope = [r for r in mapping_rows if r[1] in ("AVAILABLE", "DERIVABLE")]
    out_scope = [r for r in mapping_rows if r[1] in ("MISSING", "UNCLEAR", "PARTIAL")]

    clar_lines = [l.strip("- ").strip() for l in clarifications_section.splitlines() if l.strip()]
    clar_numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(clar_lines)) or "(none)"

    markdown = f"""# Project Workflow Document (LOCAL MOCK - not generated by live Claude)

> Generated by the local heuristic mock client for pipeline testing only.
> Re-run without `--mock` once ANTHROPIC_API_KEY is set for production-quality output.

## Document Overview
{baseline_summary or "(no baseline summary available)"}

## The Challenge
To be finalized from the requirements and human validation workbook.

## Data Sources
Customer workspace metadata paths and sources are recorded in the validation workbook.

## Our Approach / How It Works
The rulebook defines formulas. The agent maps only metadata and creates validation queries. A human validates source data in Zoho before PRD generation.

## Data Preparation
Customer team prepares source tags, fields, and approved access.

## Detailed Requirements
{chr(10).join(f"- {req_id}: {rest}" for req_id, _, rest in mapping_rows) or "(none)"}

## The Workflow
1. Customer prepares data and tagging.
2. Implementation consolidates sources and structures the P&L.
3. Ratios and dashboard are built.
4. Human testing and validation confirms the outcome.

## Estimated Effort
**Editable by human:** [Enter effort and feasibility]

## Project Cost
**Editable by human:** [Enter rate, discovery fee, and total cost]

## The Outcome
{availability_table}

### Clarifications
{clar_numbered}
"""
    return {"markdown": markdown}


_HANDLERS = {
    "TranscriptAnalysis": _transcript_analysis_handler,
    "TranscriptChunkAnalysis": _transcript_chunk_analysis_handler,
    "RequirementBaseline": _reconciliation_handler,
    "RequirementDecomposition": _decomposition_handler,
    "DataNeedSpecification": _data_needs_handler,
    "SQLDiscovery": _sql_discovery_handler,
    "GapAnalysis": _gap_analysis_handler,
    "ScopeDocument": _scope_generation_handler,
}


class MockClaudeClient:
    def __init__(self):
        self.model = "local-mock"

    def call(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        schema = _extract_trailing_schema(system_prompt)
        title = schema.get("title")
        handler = _HANDLERS.get(title)
        if handler is None:
            raise RuntimeError(f"MockClaudeClient has no handler for schema '{title}'.")
        return json.dumps(handler(system_prompt, user_prompt), indent=2)
