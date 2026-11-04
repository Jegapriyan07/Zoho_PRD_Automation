"""Stage 6: SQL Data Discovery.

Generates candidate READ-ONLY SQL queries (schema discovery / sample / count
checks) to find relevant tables and columns for each data need.
"""
from typing import Any

from pipeline.case_store import CaseStore
from pipeline.claude_client import ClaudeClient
from pipeline.json_utils import extract_json
from pipeline.models import DataNeedSpecification, SQLDiscovery
from pipeline.prompt_utils import with_schema

STAGE_NUM = 7

INSTRUCTION_HEAD = """You are a data engineer generating READ-ONLY candidate SQL queries against a \
SQLite database to validate whether the data concepts needed for each requirement can be supported \
by the schema metadata and the business metric definitions provided in the input.

You are given the full database schema below. You may ONLY reference tables and columns that \
appear in this schema - never invent a table or column name.

DATABASE SCHEMA:
"""

INSTRUCTION_TAIL = """

Rules:
- Every query must be a single SELECT statement (or PRAGMA table_info(...) for schema checks).
- Never write INSERT/UPDATE/DELETE/DROP/ALTER or any other write/DDL statement.
- Use the business metric definition / calculation logic as the source of intent. The query must be \
constructed to validate metadata support for that metric, not to guess the metric from column names.
- For each data need, identify exact metadata paths only when they appear in the supplied schema.
  Explain semantic meaning, type, grain, aggregation, relationship, and calculation suitability in
  mapping_rationale. Use DIRECT MATCH, POTENTIAL MATCH, DERIVABLE, PARTIAL MATCH, NO MATCH, or
  UNVERIFIED; a similar name alone is never a direct match.
- Do not invent a table, column, relationship, or SQL query. If the schema is empty or unavailable,
  return an empty sql string, no metadata paths, mapping_status UNVERIFIED, validation_status
  UNVERIFIED, and state "Workspace metadata not available for verification." in the rationale.
- Do not execute queries or infer data availability. The human is the only authority who checks \
whether original data exists, is complete, or is soiled.
- Tie every query back to its requirement_id.
- Respond with ONLY a single JSON object matching this schema, no prose, no markdown fences:"""


def _format_schema(schema: dict[str, list[dict[str, Any]]]) -> str:
    lines = []
    for table, cols in schema.items():
        col_desc = ", ".join(f"{c['name']} ({c['type']})" for c in cols)
        lines.append(f"- {table}: {col_desc}")
    return "\n".join(lines)


def run(
    store: CaseStore,
    claude: ClaudeClient,
    data_needs: DataNeedSpecification,
    schema: dict[str, list[dict[str, Any]]],
) -> SQLDiscovery:
    if not schema:
        discovery = SQLDiscovery(queries=[
            {
                "requirement_id": need.requirement_id,
                "purpose": "Metadata verification is required before query design.",
                "sql": "",
                "metadata_paths": [],
                "mapping_status": "UNVERIFIED",
                "mapping_rationale": "Workspace metadata not available for verification.",
                "validation_status": "UNVERIFIED",
            }
            for need in data_needs.needs
        ])
        store.save_stage(STAGE_NUM, discovery)
        return discovery

    instruction = INSTRUCTION_HEAD + _format_schema(schema) + INSTRUCTION_TAIL
    system_prompt = with_schema(instruction, SQLDiscovery)

    needs_text = "\n".join(
        f"- {need.requirement_id}: " + "; ".join(f"[{c.concept_type}] {c.concept}" for c in need.data_concepts)
        for need in data_needs.needs
    )
    user_prompt = f"DATA NEEDS:\n{needs_text}\n\nProduce the candidate SQL discovery JSON now."

    response_text = claude.call(system_prompt, user_prompt, max_tokens=8192)
    store.log_claude_call(STAGE_NUM, system_prompt, user_prompt, response_text)

    discovery = SQLDiscovery.model_validate(extract_json(response_text))
    store.save_stage(STAGE_NUM, discovery)
    return discovery
