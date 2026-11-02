"""Stage 5: Data Need Specification.

For each atomic requirement, specifies what data concepts (entities/fields/
aggregations) would be needed to satisfy it - BEFORE touching the database.
"""
from pipeline.case_store import CaseStore
from pipeline.claude_client import ClaudeClient
from pipeline.json_utils import extract_json
from pipeline.models import (
    CaseContext,
    DataConcept,
    DataNeed,
    DataNeedSpecification,
    RequirementDecomposition,
    RulebookRetrievalResult,
)
from pipeline.prompt_utils import with_schema
from pipeline.rag_mcp_client import RAGMCPClient
from pipeline.template_contract import ANALYSIS_RULES

STAGE_NUM = 6

INSTRUCTION = f"""You translate atomic requirements into the data concepts needed to satisfy them, \
using the business metric definitions or calculation logic supplied in the evidence, not guesses.

Rules:
- For each atomic requirement, list the data concepts required: candidate entities, fields, \
aggregations, joins, or specific filter values that would need to exist for this requirement to \
be satisfiable.
- The rulebook is the authoritative source for metric formulas and calculation rules. Carry its \
formula and reference into each relevant data concept. Cite supporting chunk IDs in \
rulebook_chunk_ids. If the retrieved content does not define a required metric, flag that fact in \
notes and do not invent a formula.
- Think in terms of general business data concepts (e.g. "order cancellation reason", "product \
cost", "ticket resolution timestamp"), NOT actual database table/column names - you have not seen \
the schema yet.
- Do not claim any data exists. This stage is a conceptual specification only.
- If a metric definition is missing or ambiguous, explicitly surface that as a gap and do not \
assume the calculation.
{ANALYSIS_RULES}
- Respond with ONLY a single JSON object matching this schema, no prose, no markdown fences:"""


def run(
    store: CaseStore,
    claude: ClaudeClient,
    decomposition: RequirementDecomposition,
    context: CaseContext,
    rag: RAGMCPClient,
) -> DataNeedSpecification:
    system_prompt = with_schema(INSTRUCTION, DataNeedSpecification)
    retrievals = []
    needs = []
    retrieved_requirements = rag.retrieve_many_sync(decomposition.requirements)
    for requirement, (retrieval, audit_entries) in zip(
        decomposition.requirements, retrieved_requirements
    ):
        retrievals.append(retrieval)
        for index, audit in enumerate(audit_entries, start=1):
            store.log_mcp_call(
                f"rag_search_{requirement.requirement_id}_{index}",
                audit["request"],
                audit["response"],
            )

        if retrieval.grounding_status != "GROUNDED":
            needs.append(DataNeed(
                requirement_id=requirement.requirement_id,
                data_concepts=[DataConcept(
                    concept=requirement.description,
                    concept_type="entity",
                    notes=(retrieval.message or "Rulebook retrieval failed.") +
                          " Clarify the metric definition and formula with the customer.",
                )],
            ))
            continue

        chunks_text = "\n\n".join(
            f"CHUNK ID: {chunk.chunk_id}\nSOURCE: {chunk.category} | {chunk.title} | "
            f"{chunk.heading_path} | score={chunk.score:.3f}\n{chunk.content}"
            for chunk in retrieval.chunks
        )
        user_prompt = (
            f"RETRIEVED RULEBOOK CHUNKS:\n{chunks_text}\n\n"
            f"ATOMIC REQUIREMENTS:\n- {requirement.requirement_id} [{requirement.category}]: "
            f"{requirement.description}\n\nProduce the data need specification JSON now."
        )
        response_text = claude.call(system_prompt, user_prompt)
        store.log_claude_call(
            STAGE_NUM, system_prompt, user_prompt, response_text, requirement.requirement_id
        )
        partial = DataNeedSpecification.model_validate(extract_json(response_text))
        allowed_chunk_ids = {chunk.chunk_id for chunk in retrieval.chunks}
        matching = next(
            (item for item in partial.needs if item.requirement_id == requirement.requirement_id),
            None,
        )
        if matching is None:
            matching = DataNeed(
                requirement_id=requirement.requirement_id,
                data_concepts=[DataConcept(
                    concept=requirement.description,
                    concept_type="entity",
                    notes="The reasoning model returned no data need for this requirement.",
                )],
            )
        for concept in matching.data_concepts:
            concept.rulebook_chunk_ids = [
                chunk_id for chunk_id in concept.rulebook_chunk_ids if chunk_id in allowed_chunk_ids
            ]
            if concept.metric_formula and not concept.rulebook_chunk_ids:
                concept.metric_formula = None
                concept.notes = ((concept.notes or "") +
                                 " Formula removed because no retrieved rulebook chunk cited it.").strip()
            if concept.rulebook_chunk_ids and not concept.rulebook_reference:
                citations = [
                    chunk for chunk in retrieval.chunks if chunk.chunk_id in concept.rulebook_chunk_ids
                ]
                concept.rulebook_reference = "; ".join(
                    f"{chunk.title} > {chunk.heading_path} [{chunk.chunk_id}]" for chunk in citations
                )
        needs.append(matching)

    store.save_stage(65, RulebookRetrievalResult(requirements=retrievals))
    spec = DataNeedSpecification(needs=needs)
    store.save_stage(STAGE_NUM, spec)
    return spec
