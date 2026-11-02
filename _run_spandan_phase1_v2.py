"""Run the Spandan case through Phase 1 (stages 1-7), v2: requirements grouped
at the business/dashboard level (not one requirement per metric), with each
requirement's DataNeed carrying multiple grounded metric concepts, per the
user's correction. No ANTHROPIC_API_KEY is configured, so the assistant
(Claude Sonnet, this conversation) authors the stage 3/4/5/6 reasoning
directly and feeds it through the real stage modules via ScriptedClaudeClient,
exactly as in the first Phase 1 run - only the requirement grouping and
data-concept richness changed.
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
case_id, store = stage1_intake.create_case(
    [r"C:\Users\jegap\Downloads\Spandan meeting Transcript (3).txt"],
)
print("case_id:", case_id)
context = stage2_parsing.run(store)

# ---------------------------------------------------------------------------
# Stage 3: Requirement Baseline (authored) - same baseline as before, still valid
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
        "discovery/feasibility fee followed by per-day implementation billing. The screen-share "
        "scope confirms three deliverables: Property-Level Custom P&L, Portfolio/All-Properties "
        "Comparison, and Current Assets Summary, with their specified columns, filters, and "
        "business explanations captured in the attached scope evidence."
    ),
    baseline_requirements=[
        "Build one unified property-level and portfolio-level P&L/EBITDA financial dashboard in Zoho Analytics that calculates Gross Profit, Gross Profit %, EBITDA, EBITDA %, Rent-to-Revenue ratio, Net Cash Flow (with investor interest payout and loan principal repayment moved below the EBITDA line), ROI %, and ROC %.",
        "Consolidate Zoho Books, an enhanced Zoho Books custom cash-transaction module, and external PMS/Excel occupancy and revenue data into one unified reporting layer, and calculate Occupancy % within Zoho Analytics.",
        "Apply revenue-timing proration rules (PMS pro-rates cross-month bookings by night; expenses always follow calendar month) and support a customer-supplied remapping of specific balance-sheet items into the custom P&L.",
        "Deliver a Property-Level Custom P&L with Start Date, End Date, Nights Considered, Nights Booked, Occupancy %, ADR, Account Type, Account Name, Amount, Month, Cash Expenses, Total Expenses, Gross Profit/Gross Profit %, EBITDA/EBITDA %, Rent-to-Revenue Ratio, Net Cash Flow, and ROI %/ROC %, filtered by single Property and Month/Period.",
        "Deliver a Portfolio/All-Properties Comparison with Property Name, Revenue, Gross Profit/Gross Profit %, EBITDA/EBITDA %, and Net Cash Flow, filtered by Month/Period and multi-select Property with All Properties as the default.",
        "Deliver a Current Assets Summary with Property Name, Security Deposit, Brokerage, and Setup/Photoshoot Cost Total, filtered by Property and Period and kept separate from operating P&L results.",
        "The engagement is billed as a one-time discovery/feasibility fee (credited against implementation if the project proceeds) followed by per-developer-day implementation billing, with 5-10 business days of post-delivery developer hypercare support and a one-on-one knowledge-transfer session before handover.",
    ],
    conflicts=[
        ConflictNote(
            topic="Revenue timing/source of truth",
            description=(
                "Zoho Books records revenue based on the invoice date raised by Airbnb/MakeMyTrip, "
                "which can misallocate a booking's entire value to a single month when the stay "
                "spans two months. The customer's new PMS instead pro-rates revenue by night across "
                "the actual calendar months, which the customer considers more accurate. The "
                "customer prefers PMS as the source of truth for revenue where available, falling "
                "back to Zoho Books if the PMS pipeline is not ready."
            ),
            sources=["Spandan meeting Transcript (5).txt"],
        )
    ],
)
claude_stage3 = ScriptedClaudeClient([baseline.model_dump_json()])
baseline = stage3_reconciliation.run(store, claude_stage3, context)

# ---------------------------------------------------------------------------
# Stage 4: Requirement Decomposition (authored) - grouped at business/dashboard
# level; each requirement will carry MULTIPLE metrics/data concepts in stage 5,
# not one requirement per metric.
# ---------------------------------------------------------------------------
ATOMIC = [
    ("REQ-001", "metric", "Build a unified property-level and portfolio-level financial performance dashboard that calculates Gross Profit, Gross Profit percentage, EBITDA, EBITDA percentage, Rent-to-Revenue ratio, Net Cash Flow after moving investor loan interest payout and loan principal repayment below the EBITDA line unlike Zoho Books default P&L classification, ROI percentage, and ROC percentage."),
    ("REQ-002", "business_rule", "Consolidate financial data from three sources - Zoho Books which already carries a property tag on about 70 to 80 percent of transactions, an enhanced Zoho Books custom module for manually tracked cash transactions that needs a ledger account name field and a property tag field added and should only be merged once both are present, and externally supplied PMS occupancy and revenue data via Excel CSV upload or a live cloud sheet - into one unified Zoho Analytics reporting layer, and calculate Occupancy percentage from capacity and nights booked data."),
    ("REQ-003", "business_rule", "Apply business rules to the consolidated data: pro-rate revenue by night across calendar months for bookings that span two months since the customer's new PMS export already does this so no additional Analytics side proration is required, while expenses always follow the calendar month of the transaction with no proration; prefer PMS sourced pro-rated monthly revenue over Zoho Books invoice date revenue where available since invoice date revenue can misallocate a cross month booking to a single month; and support a customer supplied remapping of specific balance sheet items such as refundable security deposit, brokerage, and photoshoot setup cost into the custom P&L."),
    ("REQ-004", "dimension", "All three reports must be navigable by an individual property, a combination of properties, or all properties combined using the existing property tag, and by a selectable Month/Period; the property-level report uses single-select Property, the portfolio report uses multi-select Property with All Properties as the default, and the current-assets report uses Property and Period filters."),
    ("REQ-005", "business_rule", "The engagement follows a two phase commercial structure: a one time discovery feasibility phase with a sample report and Statement of Work billed at a flat one time fee credited against implementation fees if the project proceeds, per developer day implementation billing with total days determined after the feasibility assessment, five to ten business days of post delivery hypercare support directly from the assigned developer, and a one on one knowledge transfer session with the assigned developer before final handover."),
]
decomposition = RequirementDecomposition(
    requirements=[AtomicRequirement(requirement_id=r, category=c, description=d) for r, c, d in ATOMIC]
)
claude_stage4 = ScriptedClaudeClient([decomposition.model_dump_json()])
decomposition = stage4_decomposition.run(store, claude_stage4, baseline)

# ---------------------------------------------------------------------------
# Stage 5: Data Need Specification - each requirement's DataNeed carries
# MULTIPLE data_concepts (metrics), citing only chunk_ids the real RAG
# retrieval actually returned for that requirement (see _preview_rag2_out.txt).
# REQ-005 is NO_MATCH and is handled automatically by stage5's fallback path.
# ---------------------------------------------------------------------------
GROUNDED_NEEDS: dict[str, DataNeedSpecification] = {}

GROUNDED_NEEDS["REQ-001"] = DataNeedSpecification(needs=[DataNeed(
    requirement_id="REQ-001",
    data_concepts=[
        DataConcept(
            concept="Property-Level Custom P&L report layout: Start Date, End Date, Nights Considered, Nights Booked, Occupancy %, ADR, Account Type, Account Name, Amount, Month, Cash Expenses, Total Expenses, Gross Profit/Gross Profit %, EBITDA/EBITDA %, Rent-to-Revenue Ratio, Net Cash Flow, ROI %/ROC %",
            concept_type="entity",
            rulebook_chunk_ids=["dc0be220cda4ce32", "6338c343cef3eb2c"],
            notes="Screen-share scope evidence defines the client-facing columns and single Property plus Month/Period filters; the P&L rulebook supports the account, amount, and time-grouping portions.",
        ),
        DataConcept(
            concept="Gross Profit = Revenue (Income accounts) - direct/COGS property expenses",
            concept_type="aggregation",
            metric_formula="Gross Profit = Revenue - COGS (direct property expenses)",
            rulebook_chunk_ids=["dc0be220cda4ce32"],
            notes="Matches the rulebook's profit/loss aggregate-formula pattern; sliced by property tag.",
        ),
        DataConcept(
            concept="Gross Profit % = Gross Profit / Revenue",
            concept_type="aggregation",
            metric_formula="Gross Profit % = Gross Profit / Revenue",
            rulebook_chunk_ids=["dc0be220cda4ce32"],
        ),
        DataConcept(
            concept="EBITDA = Gross Profit - Operating Expenses (before interest, tax, depreciation, amortization)",
            concept_type="aggregation",
            metric_formula="EBITDA = Gross Profit - Operating Expenses",
            rulebook_chunk_ids=["dc0be220cda4ce32", "6338c343cef3eb2c"],
            notes=(
                "The rulebook's P&L aggregate-formula pattern (income minus expense account base "
                "types) is the closest documented equivalent; the customer's EBITDA additionally "
                "requires excluding investor interest payout from Operating Expenses (see below) "
                "rather than netting it in, as Zoho Books does by default."
            ),
        ),
        DataConcept(
            concept="EBITDA % = EBITDA / Revenue",
            concept_type="aggregation",
            metric_formula="EBITDA % = EBITDA / Revenue",
            rulebook_chunk_ids=["dc0be220cda4ce32"],
        ),
        DataConcept(
            concept="Rent-to-Revenue ratio at the property level",
            concept_type="aggregation",
            metric_formula=None,
            rulebook_chunk_ids=[],
            notes=(
                "Not documented in the Zoho Finance rulebook - this is a customer-defined ratio "
                "(the transcript implies Rent Expense / Revenue). The exact rent-expense account(s) "
                "to use must be confirmed directly with the customer before implementation."
            ),
        ),
        DataConcept(
            concept="Below-EBITDA reclassification: exclude investor/loan interest payout from Operating Expenses and add it back as a separate below-EBITDA line",
            concept_type="filter_value",
            rulebook_chunk_ids=["4c66888db68806bb", "d08525b1fd50a386"],
            notes=(
                "Zoho Books' default P&L nets interest expense into operating income; the rulebook's "
                "Cash Flow statement separately documents Financing Activities (which includes "
                "interest/loan cash movements) apart from Operating Activities, supporting the same "
                "separation the customer wants."
            ),
        ),
        DataConcept(
            concept="Below-EBITDA loan Principal Repaid line item, sourced from balance-sheet loan liability accounts",
            concept_type="field",
            rulebook_chunk_ids=["11e4faf4272258c4", "d08525b1fd50a386"],
            notes=(
                "Principal repayment reduces a balance-sheet loan liability and is not part of the "
                "standard Zoho Books P&L; the rulebook's Balance Sheet reference documents "
                "liabilities/equity as separate from P&L income-statement accounts, confirming this "
                "must be pulled in as a separate field for the below-EBITDA cash-flow view."
            ),
        ),
        DataConcept(
            concept="Net Cash Flow = EBITDA - Interest Paid - Principal Repaid - Depreciation/Amortization (+/- other non-operating items)",
            concept_type="aggregation",
            metric_formula="Net Cash Flow = EBITDA - Interest Paid - Principal Repaid - Depreciation/Amortization (+/- other non-operating items)",
            rulebook_chunk_ids=["4c66888db68806bb", "60a03144888e160b"],
            notes="Adapted from the rulebook's Cash Flow equation (Operating + Investing + Financing activities) to the customer's EBITDA-down structure.",
        ),
        DataConcept(
            concept="ROI % = Net Cash Flow / Total Investment",
            concept_type="aggregation",
            metric_formula="ROI % = Net Cash Flow / Total Investment",
            rulebook_chunk_ids=["4c66888db68806bb", "60a03144888e160b"],
            notes="Rulebook confirms the Net Cash Flow base calculation; the investment denominator is a customer-supplied figure not present in the rulebook and must be confirmed.",
        ),
        DataConcept(
            concept="ROC % = Net Cash Flow / Total Capital Employed",
            concept_type="aggregation",
            metric_formula="ROC % = Net Cash Flow / Total Capital Employed",
            rulebook_chunk_ids=["4c66888db68806bb", "60a03144888e160b"],
            notes="Same basis as ROI %; the capital-employed denominator is a customer-supplied figure not present in the rulebook and must be confirmed.",
        ),
    ],
)])

GROUNDED_NEEDS["REQ-002"] = DataNeedSpecification(needs=[DataNeed(
    requirement_id="REQ-002",
    data_concepts=[
        DataConcept(
            concept="Portfolio/All-Properties Comparison report layout: Property Name, Revenue, Gross Profit/Gross Profit %, EBITDA/EBITDA %, Net Cash Flow",
            concept_type="entity",
            rulebook_chunk_ids=["82c88eee624871ed", "6338c343cef3eb2c"],
            notes="Screen-share scope evidence defines the portfolio comparison output and Month/Period plus multi-select Property filters; the rulebook supports consolidated and P&L report construction patterns.",
        ),
        DataConcept(
            concept="Consolidated property-level query blending Zoho Books, custom module, and PMS/Excel sources",
            concept_type="entity",
            rulebook_chunk_ids=["82c88eee624871ed", "5102343511f683df"],
            notes=(
                "Follows the same multi-source consolidation pattern documented for combining data "
                "from several organizations: bring each source into Zoho Analytics as its own table "
                "set, then JOIN/UNION them into one master query table keyed by property tag and "
                "account/ledger name."
            ),
        ),
        DataConcept(
            concept="Custom module field additions: ledger/account-name selection and property tag",
            concept_type="field",
            rulebook_chunk_ids=["6338c343cef3eb2c"],
            notes="Needs Zoho Books team support to add these two fields to the existing custom module; without them the custom-module records cannot be merged into the account-based P&L.",
        ),
        DataConcept(
            concept="Filter: only merge custom-module records once both ledger mapping and property tag are present",
            concept_type="filter_value",
            rulebook_chunk_ids=["82c88eee624871ed"],
        ),
        DataConcept(
            concept="PMS occupancy/booking data ingestion (Excel/CSV or live cloud sheet)",
            concept_type="entity",
            rulebook_chunk_ids=["0d31cbe36895e28c"],
            notes="No direct PMS-to-Analytics connector documented in the rulebook; customer will supply a periodic file (Excel/CSV or live cloud sheet) with start date, end date, nights considered, nights booked, and ADR per property/month.",
        ),
        DataConcept(
            concept="Occupancy % = Nights Booked / Available Capacity Nights",
            concept_type="aggregation",
            metric_formula="Occupancy % = Nights Booked / Available Capacity Nights",
            rulebook_chunk_ids=["0d31cbe36895e28c"],
            notes="No rulebook formula for occupancy specifically; derived directly from customer-supplied capacity and booked-nights fields once ingested.",
        ),
    ],
)])

GROUNDED_NEEDS["REQ-003"] = DataNeedSpecification(needs=[DataNeed(
    requirement_id="REQ-003",
    data_concepts=[
        DataConcept(
            concept="Current Assets Summary report layout: Property Name, Security Deposit, Brokerage, Setup/Photoshoot Cost Total, kept separate from operating P&L",
            concept_type="entity",
            rulebook_chunk_ids=["d08525b1fd50a386"],
            notes="Screen-share scope evidence defines this separate report; the Balance Sheet rulebook supports treating these as asset-side values rather than operating P&L expenses.",
        ),
        DataConcept(
            concept="Revenue proration: bookings spanning two calendar months pro-rated by night (handled by PMS export)",
            concept_type="filter_value",
            rulebook_chunk_ids=["de3f384165a0d050"],
            notes="No rulebook rule for cross-month revenue proration; the customer's new PMS already performs this pro-ration on export, so no Zoho Analytics-side proration logic is required - only ingest the pre-prorated monthly figures.",
        ),
        DataConcept(
            concept="Expenses always follow the calendar month of the transaction, no proration",
            concept_type="filter_value",
            rulebook_chunk_ids=["a6807bd70069e657"],
            notes="Matches the rulebook's standard Transaction Date-based monthly grouping for P&L expense columns.",
        ),
        DataConcept(
            concept="Revenue source precedence: PMS pro-rated revenue preferred over Zoho Books invoice-date revenue",
            concept_type="filter_value",
            rulebook_chunk_ids=["6338c343cef3eb2c"],
            notes="No rulebook rule for this precedence; customer-specific business rule captured directly from the meeting - use PMS revenue when available, else fall back to Zoho Books invoice-date revenue.",
        ),
        DataConcept(
            concept="Customer-supplied remapping of specific balance-sheet items (refundable security deposit, brokerage, photoshoot setup cost) into the custom P&L",
            concept_type="join",
            rulebook_chunk_ids=[],
            notes="Not documented in the rulebook - requires a customer-supplied mapping list (which Zoho Books ledger/account maps to which line in the custom P&L) before implementation.",
        ),
    ],
)])

GROUNDED_NEEDS["REQ-004"] = DataNeedSpecification(needs=[DataNeed(
    requirement_id="REQ-004",
    data_concepts=[
        DataConcept(
            concept="Property dimension for navigation (single property, combination, or all properties)",
            concept_type="field",
            rulebook_chunk_ids=["ab67785891cfae81"],
            notes="Uses the property tag already applied to Zoho Books entries; the same tag must be present on custom-module and PMS records to slice consistently.",
        ),
        DataConcept(
            concept="Time-period dimension for navigation (month, custom range)",
            concept_type="field",
            rulebook_chunk_ids=["de3f384165a0d050", "f262f60cfed2f7a9", "aec18cc771e910a5"],
            notes="Rulebook's Timeline reference (MTD/QTD/YTD/MOM/QOQ formulas) provides the Zoho Analytics date-filtering patterns to reuse for period navigation.",
        ),
    ],
)])

grounded_order = [r for r, _, _ in ATOMIC if r in GROUNDED_NEEDS]
claude_stage5 = ScriptedClaudeClient([GROUNDED_NEEDS[r].model_dump_json() for r in grounded_order])
data_needs = stage5_data_needs.run(
    store, claude_stage5, decomposition, context,
    __import__("pipeline.rag_mcp_client", fromlist=["RAGMCPClient"]).RAGMCPClient(),
)
retrieval = store.load_stage(65, RulebookRetrievalResult)

# ---------------------------------------------------------------------------
# Stage 6: no live Zoho Analytics workspace yet - skip live metadata mapping.
# ---------------------------------------------------------------------------
claude_stage6 = ScriptedClaudeClient(['{"queries": []}'])
sql_discovery = stage6_sql_discovery.run(store, claude_stage6, data_needs, {})

# ---------------------------------------------------------------------------
# Stage 7: Excel validation workbook (real)
# ---------------------------------------------------------------------------
workbook_path = stage7_validation_workbook.run(store, decomposition, data_needs, sql_discovery, retrieval)
print("workbook:", workbook_path)
print("case_id:", case_id)
