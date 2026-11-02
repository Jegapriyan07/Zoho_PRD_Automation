"""Stage 4: Client requirement grouping.

Converts the reconciled baseline into a small set of client-owned requirement
units for PRD and estimation. Each unit may contain multiple metrics, data
sources, dimensions, filters, and business rules.
"""
from pipeline.case_store import CaseStore
from pipeline.claude_client import ClaudeClient
from pipeline.json_utils import extract_json
from pipeline.models import RequirementBaseline, RequirementDecomposition
from pipeline.prompt_utils import with_schema
from pipeline.template_contract import ANALYSIS_RULES

STAGE_NUM = 5

INSTRUCTION = f"""You convert a reconciled client requirement baseline into a small set of coherent, \
client-owned requirement units for a data/analytics scoping engagement and client-facing PRD.

Rules:
- Do not copy baseline sentences mechanically. Synthesize the full context into coherent requirement \
units that describe the client's intended outcome.
- Prefer one requirement per meaningful business outcome or report/workflow, usually around 3-8 \
requirements for a normal discovery call. Do not create one row per transcript sentence or one row \
per metric.
- A single requirement may and often should contain multiple metrics, dimensions, filters, source \
systems, formulas, and acceptance conditions. Keep those together when they serve the same outcome, \
such as one P&L dashboard requirement containing Gross Profit, EBITDA, ROI, and property/time filters.
- Exclude internal analyst dialogue, delivery process, trial-extension logistics, and unagreed commercial \
discussion unless the baseline explicitly identifies it as a client-approved scope or deliverable.
- Each requirement must be a complete, unambiguous client need that can be traced to the baseline and \
later expanded into multiple RAG-grounded data concepts.
- Classify each requirement into exactly one category allowed by the schema: metric, filter, \
time_logic, or business_rule. Use the category of the primary outcome; do not split a bundled \
requirement merely because it contains secondary dimensions or time logic.
- Assign sequential ids starting at REQ-001, REQ-002, ... in the order you list them.
- Do not invent requirements beyond what the baseline supports. If a baseline requirement bundles \
several concerns that belong to one business outcome, preserve them in one requirement description.
- Populate evidence, source_systems, report_surfaces, acceptance_criteria, validation_method, and dependencies
  for every requirement. These are the traceability contract consumed by the validation book and PRD.
{ANALYSIS_RULES}
- Respond with ONLY a single JSON object matching this schema, no prose, no markdown fences:"""


def run(store: CaseStore, claude: ClaudeClient, baseline: RequirementBaseline) -> RequirementDecomposition:
    system_prompt = with_schema(INSTRUCTION, RequirementDecomposition)
    user_prompt = (
        f"BASELINE SUMMARY:\n{baseline.summary}\n\n"
        "BASELINE REQUIREMENTS:\n" + "\n".join(f"- {r}" for r in baseline.baseline_requirements) +
        f"\n\nOBJECTIVES:\n{baseline.objectives}\nSCOPE:\n{baseline.in_scope}\n"
        f"REPORTS:\n{[report.model_dump() for report in baseline.reports]}\n"
        f"METRICS:\n{[metric.model_dump() for metric in baseline.metrics]}\n"
        "\n\nProduce the atomic requirement decomposition JSON now."
    )

    response_text = claude.call(system_prompt, user_prompt)
    store.log_claude_call(STAGE_NUM, system_prompt, user_prompt, response_text)

    decomposition = RequirementDecomposition.model_validate(extract_json(response_text))
    store.save_stage(STAGE_NUM, decomposition)
    return decomposition
