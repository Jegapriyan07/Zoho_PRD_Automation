"""Run the Spandan case through Phase 1 (stages 1-7) end-to-end.

Stages 3, 4, and 5 normally call the Anthropic API through ClaudeClient, but no
ANTHROPIC_API_KEY is configured in this project. Per the user's direction, the
assistant (Claude Sonnet, in this same conversation) performs that reasoning
itself instead of a mock heuristic, and this script feeds those authored,
schema-valid JSON responses into the *real* stage modules (so validation,
audit logging, and file I/O all run unmodified). Stage 5's RAG retrieval is
real (calls the local RAG MCP server) - only the per-requirement reasoning
text that would normally come from the Claude API is supplied here, and only
citing chunk_ids that retrieval actually returned. Stage 6 has no live Zoho
Analytics workspace to query yet (brand-new prospect), so it runs with an
empty metadata schema, matching the prior case's behavior.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import stage1_intake, stage2_parsing, stage6_sql_discovery, stage7_validation_workbook
from pipeline import stage3_reconciliation, stage4_decomposition, stage5_data_needs
from pipeline.models import (
    AtomicRequirement,
    ConflictNote,
    DataConcept,
    DataNeed,
    DataNeedSpecification,
    RequirementBaseline,
    RequirementDecomposition,
    RulebookRetrievalResult,
)


class ScriptedClaudeClient:
    """Drop-in ClaudeClient replacement that returns pre-authored JSON in call order."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._i = 0

    def call(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        resp = self._responses[self._i]
        self._i += 1
        return resp


# ---------------------------------------------------------------------------
# Stage 1 + 2 (real, deterministic)
# ---------------------------------------------------------------------------
case_id, store = stage1_intake.create_case(["sample_case/spandan_transcript.txt"])
print("case_id:", case_id)
context = stage2_parsing.run(store)

# ---------------------------------------------------------------------------
# Stage 3: Requirement Baseline (authored)
# ---------------------------------------------------------------------------
baseline = RequirementBaseline(
    summary=(
        "A short-term rental / serviced-property operator (~30-33 properties) wants to replace "
        "its manual Excel-based P&L tracking with a unified, property-level financial dashboard in "
        "Zoho Analytics. Roughly 70-80% of transactions are already recorded in Zoho Books with a "
        "property tag on each entry. The remaining data comes from two other sources: (1) a Zoho "
        "Books custom module used to record cash-only expenses/income that cannot be entered as "
        "normal Zoho Books transactions, and (2) an external Property Management System (PMS) that "
        "tracks occupancy, bookings, and (optionally) revenue, currently exported to Excel. The "
        "customer wants Gross Profit, EBITDA, and related ratios calculated per property and "
        "portfolio-wide, with investor interest payouts and loan principal repayments moved below "
        "the EBITDA line (unlike Zoho Books' default classification), plus Net Cash Flow, ROI%, and "
        "ROC%. A discovery-phase proof of concept was previously attempted with a partner but did "
        "not fully meet requirements; the vendor now proposes a two-phase engagement: a one-time "
        "discovery/feasibility fee followed by per-day implementation billing."
    ),
    baseline_requirements=[
        "Consolidate Zoho Books, a Zoho Books custom cash-transaction module, and external PMS/Excel data into one unified property-level P&L in Zoho Analytics.",
        "Calculate Gross Profit and Gross Profit % (Revenue minus direct operating expenses, divided by Revenue) at the property level.",
        "Calculate EBITDA and EBITDA % (operating profit before interest, tax, depreciation, and amortization, divided by Revenue) at the property level.",
        "Calculate a Rent-to-Revenue ratio at the property level.",
        "Classify investor/loan interest payout as a below-EBITDA item rather than an operating expense, and include loan Principal Repaid as a below-EBITDA cash-flow deduction even though Zoho Books' standard P&L excludes both.",
        "Calculate Net Cash Flow (EBITDA minus interest paid minus principal repaid minus depreciation/amortization) and use it to calculate ROI % and ROC %.",
        "Support a customer-supplied remapping of specific balance-sheet items (e.g. refundable security deposit, brokerage, photoshoot setup cost) into the custom P&L.",
        "The report must be navigable by individual property, a combination of properties, or all properties combined, and by a selectable time period.",
        "Enhance the existing Zoho Books custom module (used for manually tracked cash transactions) to add a ledger/account-name field and a property tag field, both currently missing, and only merge records once both are present.",
        "Bring in PMS occupancy and booking data (start date, end date, nights considered, nights booked, ADR) via an uploaded Excel/CSV file or a live cloud sheet, not a direct system integration, for the initial phase; calculate Occupancy % within Zoho Analytics from capacity and nights-booked data.",
        "Revenue for bookings spanning two calendar months must be pro-rated by night across those months (handled by the customer's new PMS export); expenses always follow the calendar month with no proration; prefer PMS-sourced pro-rated revenue over Zoho Books' invoice-date-based revenue where available.",
        "The engagement is billed as a one-time discovery/feasibility fee (credited against implementation if the project proceeds) followed by per-developer-day implementation billing, with 5-10 business days of post-delivery developer hypercare support and a one-on-one knowledge-transfer session before handover.",
    ],
    conflicts=[
        ConflictNote(
            topic="Revenue timing/source of truth",
            description=(
                "Zoho Books records revenue based on the invoice date raised by Airbnb/MakeMyTrip, "
                "which can misallocate a booking's entire value to a single month when the stay "
                "spans two months. The customer's new PMS instead pro-rates revenue by night across "
                "the actual calendar months, which the customer considers more accurate. Both "
                "sources capture revenue; the customer prefers PMS as the source of truth for "
                "revenue where available, falling back to Zoho Books if the PMS pipeline is not "
                "ready."
            ),
            sources=["Spandan meeting Transcript (5).txt"],
        )
    ],
)
claude_stage3 = ScriptedClaudeClient([baseline.model_dump_json()])
baseline = stage3_reconciliation.run(store, claude_stage3, context)

# ---------------------------------------------------------------------------
# Stage 4: Atomic Requirement Decomposition (authored)
# ---------------------------------------------------------------------------
ATOMIC = [
    ("REQ-001", "business_rule", "Consolidate financial data from three sources - Zoho Books, a Zoho Books custom module for manually tracked cash transactions, and external PMS/Excel data - into one unified property-level P&L reporting layer in Zoho Analytics."),
    ("REQ-002", "metric", "Calculate Gross Profit as Revenue minus direct operating expenses, at the property level."),
    ("REQ-003", "metric", "Calculate Gross Profit percentage as Gross Profit divided by Revenue."),
    ("REQ-004", "metric", "Calculate EBITDA (operating profit before interest, tax, depreciation and amortization) at the property level."),
    ("REQ-005", "metric", "Calculate EBITDA percentage as EBITDA divided by Revenue."),
    ("REQ-006", "metric", "Calculate Rent-to-Revenue ratio at the property level."),
    ("REQ-007", "business_rule", "Classify investor/loan interest payout as a below-EBITDA line item rather than an operating expense, deviating from Zoho Books' default P&L classification which nets interest into operating income."),
    ("REQ-008", "business_rule", "Include Principal Repaid (loan repayment) as a below-EBITDA cash-flow deduction, even though Zoho Books' standard P&L excludes it because it is a balance-sheet item there."),
    ("REQ-009", "metric", "Calculate Net Cash Flow as EBITDA minus interest paid minus principal repaid minus depreciation and amortization, plus or minus other non-operating items."),
    ("REQ-010", "metric", "Calculate ROI percentage (Return on Investment) using Net Cash Flow."),
    ("REQ-011", "metric", "Calculate ROC percentage (Return on Capital) using Net Cash Flow."),
    ("REQ-012", "business_rule", "Support a customer-supplied remapping of specific balance-sheet items, such as refundable security deposit, brokerage, and photoshoot setup cost, into the custom P&L calculation."),
    ("REQ-013", "dimension", "Report must be navigable by an individual property, a combination of properties, or all properties combined, using the existing property tag applied to Zoho Books entries."),
    ("REQ-014", "time_logic", "Report must be navigable and filterable by a selectable time period such as a specific month or a date range."),
    ("REQ-015", "business_rule", "Enhance the existing Zoho Books custom module used for manually tracked cash transactions to add a ledger/account-name selection field and a property tag field, both currently missing."),
    ("REQ-016", "filter", "Only merge custom-module cash-transaction records into the unified P&L once they carry both an account/ledger mapping and a property tag."),
    ("REQ-017", "business_rule", "Bring in PMS occupancy and booking data (start date, end date, nights considered, nights booked, ADR) via an uploaded Excel/CSV file or a live cloud sheet rather than a direct system-to-system PMS integration, for the initial phase."),
    ("REQ-018", "metric", "Calculate Occupancy percentage from capacity and nights-booked data within Zoho Analytics rather than requiring the customer to pre-calculate it."),
    ("REQ-019", "time_logic", "Revenue for bookings spanning two calendar months must be pro-rated by night across those months; expenses always follow the calendar month of the transaction with no proration."),
    ("REQ-020", "business_rule", "Prefer PMS-sourced, pro-rated monthly revenue over Zoho-Books-invoice-date revenue where available, since Zoho Books' invoice-date-based revenue can misallocate a cross-month booking's full amount to a single month."),
    ("REQ-021", "business_rule", "Engagement follows two priced phases: a one-time discovery/feasibility phase (sample report plus Statement of Work) billed at a flat one-time fee, credited against implementation fees if the project proceeds."),
    ("REQ-022", "business_rule", "Implementation is billed on a per-developer-day basis, with total days determined after the feasibility assessment."),
    ("REQ-023", "business_rule", "Provide five to ten business days of post-delivery hypercare support directly from the assigned developer, followed by standard Zoho Analytics support."),
    ("REQ-024", "business_rule", "Provide a one-on-one knowledge-transfer session with the assigned developer covering every implemented report item before final handover."),
]
decomposition = RequirementDecomposition(
    requirements=[AtomicRequirement(requirement_id=r, category=c, description=d) for r, c, d in ATOMIC]
)
claude_stage4 = ScriptedClaudeClient([decomposition.model_dump_json()])
decomposition = stage4_decomposition.run(store, claude_stage4, baseline)

# ---------------------------------------------------------------------------
# Stage 5: Data Need Specification (real RAG retrieval, authored reasoning)
# ---------------------------------------------------------------------------
# Requirement IDs confirmed GROUNDED against the RAG store (see _preview_rag.py
# output); NO_MATCH ones (REQ-006, 012, 019, 022, 023, 024) are handled
# automatically by stage5's fallback path and need no scripted response.
GROUNDED_NEEDS: dict[str, DataNeedSpecification] = {}


def need(req_id: str, concept: str, concept_type: str, chunk_ids: list[str],
         formula: str | None = None, notes: str | None = None) -> None:
    GROUNDED_NEEDS[req_id] = DataNeedSpecification(needs=[DataNeed(
        requirement_id=req_id,
        data_concepts=[DataConcept(
            concept=concept, concept_type=concept_type, notes=notes,
            metric_formula=formula, rulebook_chunk_ids=chunk_ids,
        )],
    )])


need(
    "REQ-001",
    "Consolidated property-level P&L query blending Zoho Books, custom module, and PMS/Excel sources",
    "entity", ["82c88eee624871ed"],
    notes=(
        "Follows the same multi-source consolidation pattern documented for combining data from "
        "several organizations: bring each source into Zoho Analytics as its own table set, then "
        "JOIN/UNION them into one master query table keyed by property tag and account/ledger name."
    ),
)
need(
    "REQ-002",
    "Gross Profit aggregate formula on the consolidated Accrual Transactions / custom-module table",
    "aggregation", ["dc0be220cda4ce32", "8ddfe91a3a5c640e"],
    formula="Gross Profit = Revenue (Income accounts) - Cost of Goods Sold / direct property expenses",
    notes="Matches the rulebook's profit/loss aggregate-formula pattern; sliced by property tag.",
)
need(
    "REQ-003",
    "Gross Profit % aggregate formula",
    "aggregation", ["dc0be220cda4ce32", "773ebd51472375d5"],
    formula="Gross Profit % = Gross Profit / Revenue",
)
need(
    "REQ-004",
    "EBITDA aggregate formula (rulebook calls the equivalent line 'Operating Income')",
    "aggregation", ["981d1222af7c5efe"],
    formula="EBITDA = Gross Profit - Operating Expenses (before interest, tax, depreciation, amortization)",
    notes=(
        "The rulebook's P&L structure documents this exact cascade under 'Operating Income (EBIT)'; "
        "the customer's EBITDA additionally requires moving interest payout below this line (see "
        "REQ-007) rather than netting it into operating expenses as Zoho Books does by default."
    ),
)
need(
    "REQ-005",
    "EBITDA % aggregate formula",
    "aggregation", ["dc0be220cda4ce32"],
    formula="EBITDA % = EBITDA / Revenue",
    notes="Low-confidence match; formula follows the same ratio pattern as Gross Profit %.",
)
need(
    "REQ-007",
    "Below-EBITDA reclassification of investor/loan interest payout",
    "filter_value", ["4c66888db68806bb", "6338c343cef3eb2c"],
    notes=(
        "Zoho Books' default P&L nets interest expense into operating income; per the customer's "
        "requirement, filter interest-payout account(s) OUT of the Operating Expenses aggregate and "
        "add them back as a separate below-EBITDA line, consistent with the rulebook's Cash Flow "
        "statement, which also separates financing-activity interest from operating activities."
    ),
)
need(
    "REQ-008",
    "Below-EBITDA loan Principal Repaid line item",
    "field", ["6338c343cef3eb2c", "4c66888db68806bb"],
    notes=(
        "Principal repayment reduces a balance-sheet loan liability and is not part of the standard "
        "Zoho Books P&L; it must be pulled in as a separate field/account for the below-EBITDA cash "
        "flow view, the same way the rulebook treats financing-activity cash movements separately "
        "from the P&L."
    ),
)
need(
    "REQ-009",
    "Net Cash Flow aggregate formula",
    "aggregation", ["4c66888db68806bb", "60a03144888e160b"],
    formula="Net Cash Flow = EBITDA - Interest Paid - Principal Repaid - Depreciation/Amortization (+/- other non-operating items)",
    notes="Adapted from the rulebook's Cash Flow equation (Operating + Investing + Financing activities) to the customer's EBITDA-down structure.",
)
need(
    "REQ-010",
    "ROI % aggregate formula using Net Cash Flow",
    "aggregation", ["4c66888db68806bb", "60a03144888e160b"],
    formula="ROI % = Net Cash Flow / Total Investment",
    notes="Rulebook confirms the Net Cash Flow base calculation; the investment denominator is a customer-supplied figure not present in the rulebook and must be confirmed.",
)
need(
    "REQ-011",
    "ROC % aggregate formula using Net Cash Flow",
    "aggregation", ["4c66888db68806bb", "60a03144888e160b"],
    formula="ROC % = Net Cash Flow / Total Capital Employed",
    notes="Same basis as ROI %; the capital-employed denominator is a customer-supplied figure not present in the rulebook and must be confirmed.",
)
need(
    "REQ-013",
    "Property dimension for navigation (single, combination, or all properties)",
    "field", ["6338c343cef3eb2c"],
    notes="Uses the property tag already applied to Zoho Books entries; the same tag must be present on custom-module and PMS records to slice consistently.",
)
need(
    "REQ-014",
    "Time-period dimension for navigation (month, custom range)",
    "field", ["de3f384165a0d050", "f262f60cfed2f7a9", "aec18cc771e910a5"],
    notes="Rulebook's Timeline reference (MTD/QTD/YTD/MOM/QOQ formulas) provides the Zoho Analytics date-filtering patterns to reuse for period navigation.",
)
need(
    "REQ-015",
    "Custom module field additions: ledger/account-name selection and property tag",
    "field", ["6338c343cef3eb2c", "d08525b1fd50a386"],
    notes="Needs Zoho Books team support to add these two fields to the existing custom module; without them the custom-module records cannot be merged into the account-based P&L.",
)
need(
    "REQ-016",
    "Filter: only merge custom-module records with both ledger mapping and property tag present",
    "filter_value", ["82c88eee624871ed", "6338c343cef3eb2c"],
)
need(
    "REQ-017",
    "PMS occupancy/booking data ingestion (Excel/CSV or cloud sheet)",
    "entity", ["de3f384165a0d050"],
    notes="No direct PMS-to-Analytics connector documented in the rulebook; customer will supply a periodic file (Excel/CSV or live cloud sheet) with start date, end date, nights considered, nights booked, and ADR per property/month.",
)
need(
    "REQ-018",
    "Occupancy % aggregate formula derived from capacity and nights-booked data",
    "aggregation", ["98b085ac6cb43497"],
    formula="Occupancy % = Nights Booked / Available Capacity Nights",
    notes="Adapted from the rulebook's Utilization % pattern (Actual / Available), applied to booked vs available property-nights instead of hours.",
)
need(
    "REQ-020",
    "Revenue source precedence: PMS pro-rated revenue preferred over Zoho Books invoice-date revenue",
    "filter_value", ["6338c343cef3eb2c"],
    notes="No rulebook rule for this precedence; it is a customer-specific business rule captured directly from the meeting - use PMS revenue when available, else fall back to Zoho Books invoice-date revenue.",
)
need(
    "REQ-021",
    "Engagement pricing structure (discovery fee credited against implementation)",
    "entity", ["f262f60cfed2f7a9"],
    notes="Commercial/process term, not a Zoho Analytics data concept - one-time discovery/feasibility fee of INR 10,000, credited toward implementation fees if the project proceeds.",
)

grounded_order = [r for r, _, _ in ATOMIC if r in GROUNDED_NEEDS]
claude_stage5 = ScriptedClaudeClient([GROUNDED_NEEDS[r].model_dump_json() for r in grounded_order])
data_needs = stage5_data_needs.run(store, claude_stage5, decomposition, context, __import__("pipeline.rag_mcp_client", fromlist=["RAGMCPClient"]).RAGMCPClient())
retrieval = store.load_stage(65, RulebookRetrievalResult)

# ---------------------------------------------------------------------------
# Stage 6: no live Zoho Analytics workspace yet for this brand-new prospect -
# skip live metadata mapping (empty schema), matching the user's decision.
# ---------------------------------------------------------------------------
claude_stage6 = ScriptedClaudeClient(['{"queries": []}'])
sql_discovery = stage6_sql_discovery.run(store, claude_stage6, data_needs, {})

# ---------------------------------------------------------------------------
# Stage 7: Excel validation workbook (real)
# ---------------------------------------------------------------------------
workbook_path = stage7_validation_workbook.run(store, decomposition, data_needs, sql_discovery, retrieval)
print("workbook:", workbook_path)
print("case_id:", case_id)
