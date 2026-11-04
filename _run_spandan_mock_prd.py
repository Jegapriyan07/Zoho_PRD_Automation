"""Run the Spandan case from the existing workbook through mock stages 6-10.

This uses sample_case/workspace_metadata.json only. No customer rows are read.
The generated case is a copy of the analyzed case with mock validation values.
"""
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from adapters.metadata_file_adapter import MetadataFileAdapter
from pipeline import stage6_sql_discovery, stage7_validation_workbook
from pipeline import stage8_human_validation, stage9_gap_analysis, stage10_scope_generation
from pipeline.case_store import CaseStore
from pipeline.mock_claude_client import MockClaudeClient
from pipeline.models import (
    DataNeedSpecification,
    GapAnalysis,
    HumanValidationResult,
    RequirementBaseline,
    RequirementDecomposition,
    RulebookRetrievalResult,
    SQLDiscovery,
)


ROOT = Path(__file__).resolve().parent
SOURCE_CASE_ID = "case_20261029_153754_9dbcb4"


class ScriptedClaudeClient:
    def __init__(self, response: str):
        self.response = response

    def call(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        return self.response


def _new_case() -> tuple[str, CaseStore]:
    case_id = f"case_{datetime.now().strftime('%Y%m%d_%H%M%S')}_mock_{uuid.uuid4().hex[:6]}"
    source = ROOT / "cases" / SOURCE_CASE_ID
    target = ROOT / "cases" / case_id
    shutil.copytree(source, target)
    store = CaseStore(case_id, base_dir=str(ROOT / "cases"))
    return case_id, store


def _mock_validate_workbook(store: CaseStore) -> None:
    path = store.artifact_path("validation_workbook.xlsx")
    workbook = load_workbook(path)
    matrix = workbook["Validation Matrix"]
    for row in matrix.iter_rows(min_row=2):
        if row[0].value:
            row[10].value = "Available"
            row[11].value = "MOCK ONLY: metadata/query shape checked against sample schema; no customer rows accessed."
            row[12].value = "MOCK ASSUMPTION: customer confirms the mapped sample fields and formulas for PRD demonstration."
    gaps = workbook["Gaps & Clarifications"]
    for row in gaps.iter_rows(min_row=2):
        if row[1].value:
            row[2].value = "MOCK ASSUMPTION: use the transcript definition and sample metadata for this PRD demonstration; confirm with customer before implementation."
    workbook.save(path)


def _answer_new_gap_questions(store: CaseStore) -> None:
    path = store.artifact_path("validation_workbook.xlsx")
    workbook = load_workbook(path)
    gaps = workbook["Gaps & Clarifications"]
    for row in gaps.iter_rows(min_row=2):
        if row[1].value and not row[2].value:
            row[2].value = "MOCK ASSUMPTION: pending customer confirmation; included as an editable clarification in this demo."
    workbook.save(path)


def _prd_response() -> str:
    markdown = """# Client Project Requirements Document

## Document Overview
This proof-of-concept scope describes a Zoho Analytics reporting solution for a short-term rental and serviced-property portfolio. It consolidates Zoho Books financial metadata, cash-transaction records, and PMS booking metrics into property-level and portfolio-level reporting. This document is generated from the two Spandan discovery meetings and sample workspace metadata only.

### Purpose
To provide one property-level and portfolio-level view of financial performance, occupancy, cash flow, and current assets without manually reconciling multiple systems.

### What this document covers
- The challenge
- Data sources
- The reporting approach
- Data preparation
- Detailed report requirements
- Delivery workflow, effort, cost, and outcome

### Intended audience
Business stakeholders and the implementation team reviewing the scope and validating the proposed reporting solution.

## The Challenge
The current process combines Zoho Books with manually maintained Excel records. Zoho Books captures most transactions, but cash items, PMS occupancy metrics, cross-month booking revenue, current assets, and below-EBITDA cash movements require a unified reporting view. The proposed solution must preserve property-level analysis while supporting portfolio comparison and clear monthly reporting.

## Data Sources
| Source | Mock tables or fields | Intended use |
|---|---|---|
| Zoho Books | Invoices: Invoice Date, Amount, Status, Property | Revenue and invoice metadata |
| Zoho Books Custom Module | Properties: Property Name, Security Deposit, Brokerage, Setup Cost | Property master and current-assets summary |
| PMS / Zoho Analytics | Bookings: Property, Check In, Check Out, ADR | Booking, occupancy, and PMS revenue inputs |
| Cash transaction custom module | Ledger/account name, property tag, amount, transaction date | Cash income and expense consolidation |

## Our Approach / How It Works
Create a reporting layer that joins sources by property and reporting period, keeps source-specific records identifiable, and applies the agreed business rules through calculated fields and aggregate formulas. PMS monthly revenue is preferred where available because it is already prorated across calendar months. Zoho Books revenue is the fallback source.

## Data Preparation
The customer team must maintain a property tag and ledger/account mapping for cash transactions. PMS exports should contain property, month, nights considered, nights booked, capacity, ADR, and prorated revenue where available. Account remapping for interest, principal repayment, security deposits, brokerage, and setup costs must be confirmed before implementation.

## Detailed Requirements
The following reports make up the dashboard. The columns and filters are taken from the validation workbook and the transcript-derived scope.

### Property-Level Custom P&L
| Report Name | Columns | Filters | Report Explanation |
|---|---|---|---|
| Property-Level Custom P&L | Start Date; End Date; Nights Considered; Nights Booked; Occupancy %; ADR; Account Type; Account Name; Amount; Month; Cash Expenses; Total Expenses; Gross Profit / Gross Profit %; EBITDA / EBITDA %; Rent-to-Revenue Ratio; Net Cash Flow; ROI % / ROC % | Property (single-select); Month/Period | Replaces the manually maintained P&L for one property and period. Separates operating performance from investor payouts and loan repayments. |

### Portfolio / All-Properties Comparison
| Report Name | Columns | Filters | Report Explanation |
|---|---|---|---|
| Portfolio / All-Properties Comparison | Property Name; Revenue; Gross Profit / Gross Profit %; EBITDA / EBITDA %; Net Cash Flow | Month/Period; Property (multi-select, default: All Properties) | Compares operating performance across any property combination or the full portfolio for a selected period. |

### Current Assets Summary
| Report Name | Columns | Filters | Report Explanation |
|---|---|---|---|
| Current Assets Summary | Property Name; Security Deposit; Brokerage; Setup/Photoshoot Cost Total | Property; Period | Shows upfront, non-operating property costs separately so they do not distort operating P&L results. |

### Cross-report rules and validation
| ID | Requirement | Formula / data logic | Mock validation | Feasibility | Estimated Effort |
|---|---|---|---|---|---|
| REQ-001 | Property-level and portfolio-level financial performance | Gross Profit = Revenue - direct expenses; EBITDA excludes interest, tax, depreciation, and amortization; Net Cash Flow subtracts interest, principal, and depreciation | Available against sample metadata shape; no rows accessed | [Editable] | [Editable] |
| REQ-002 | Consolidate Zoho Books, cash custom module, and PMS/Excel data | Join or union by property, account/ledger, and reporting period; Occupancy % = Nights Booked / Available Capacity Nights | Available against sample metadata shape; no rows accessed | [Editable] | [Editable] |
| REQ-003 | Apply revenue timing, expense timing, and current-assets rules | PMS revenue is monthly prorated; expenses follow calendar month; current assets remain separate from operating P&L | Mock business-rule validation; customer confirmation required | [Editable] | [Editable] |
| REQ-004 | Support property and period navigation | Single property, multi-property, all-properties default, and selectable month/period filters | Available against sample Property and date fields | [Editable] | [Editable] |
| REQ-005 | Define discovery, implementation, hypercare, and knowledge transfer | Discovery fee and implementation day rate preserved from transcript; duration and total remain editable | Documented delivery requirement | [Editable] | [Editable] |

## The Workflow
| Step | Activity | Owner / Effort |
|---|---|---|
| 1 | Data and tagging preparation: configure custom-module fields, property tags, account mappings, and the agreed PMS export format. | Customer team / Not billed |
| 2 | Data consolidation and custom P&L structuring across Zoho Books, cash transactions, current assets, and PMS data. | Implementation team / [Editable] |
| 3 | Ratios and dashboard build for property, portfolio, period, occupancy, EBITDA, cash flow, ROI, and ROC views. | Implementation team / [Editable] |
| 4 | Testing and validation against a sample property and period using read-only queries and customer review. | Both teams / [Editable] |
| 5 | Handover, one-on-one knowledge transfer, and direct developer hypercare for 5-10 business days. | Implementation team / Included in agreed scope |

## Estimated Effort
| Step | Activity | Effort |
|---|---|---|
| 1 | Data and tagging preparation | By customer team (not billed) |
| 2 | Data consolidation and custom P&L structuring | [Editable] |
| 3 | Ratios and dashboard build | [Editable] |
| 4 | Testing and validation | [Editable] |
| | Total billed effort | [Editable] |

Feasibility and effort must be confirmed after the real workspace schema and sample records are reviewed.

## Project Cost
| Item | Amount |
|---|---|
| Discovery / feasibility fee | INR 10,000 as stated in the transcript |
| Implementation day rate | INR 30,000 per developer day as stated in the transcript |
| Implementation duration | [Editable] |
| Implementation cost | [Editable] |
| Discovery fee credit if implementation proceeds | Subject to approved commercial proposal |
| Total project cost | [Editable] |

The transcript also describes a one-on-one knowledge-transfer session and 5-10 business days of developer hypercare after delivery.

## The Outcome
The expected outcome is a property-aware Zoho Analytics reporting solution with a custom P&L, portfolio comparison, current-assets summary, monthly filtering, transparent formulas, and a human validation trail. This mock PRD demonstrates document generation only and must not be treated as evidence that customer data is available or that implementation feasibility is confirmed.

### Mock Assumptions Requiring Confirmation
- Confirm the exact Zoho Books custom-module fields for ledger/account mapping and property tagging.
- Confirm the denominator definitions for ROI and ROC.
- Confirm the final account remapping for rent, interest, principal repayment, security deposit, brokerage, and setup cost.
- Confirm whether PMS revenue or Zoho Books revenue is authoritative when both are present.
"""
    return json.dumps({"markdown": markdown})


def main() -> None:
    case_id, store = _new_case()
    store.ensure_dirs()
    baseline = store.load_stage(3, RequirementBaseline)
    decomposition = store.load_stage(4, RequirementDecomposition)
    data_needs = store.load_stage(5, DataNeedSpecification)
    retrieval = store.load_stage(65, RulebookRetrievalResult)

    metadata = MetadataFileAdapter(str(ROOT / "sample_case" / "workspace_metadata.json"))
    sql_discovery = stage6_sql_discovery.run(
        store, MockClaudeClient(), data_needs, metadata.as_schema()
    )
    stage7_validation_workbook.run(store, decomposition, data_needs, sql_discovery, retrieval)
    _mock_validate_workbook(store)

    validation = stage8_human_validation.run(store)
    gap_analysis = stage9_gap_analysis.run(
        store, MockClaudeClient(), validation, decomposition, data_needs
    )
    stage7_validation_workbook.append_gap_questions(store, gap_analysis)
    _answer_new_gap_questions(store)
    gap_analysis = store.load_stage(9, GapAnalysis)

    stage10_scope_generation.run(
        store,
        ScriptedClaudeClient(_prd_response()),
        baseline,
        decomposition,
        data_needs,
        validation,
        gap_analysis,
    )
    print(f"case_id: {case_id}")
    print(f"workbook: {store.artifact_path('validation_workbook.xlsx')}")
    print(f"prd_markdown: {store.artifact_path('prd_draft.md')}")
    print(f"prd_word: {store.artifact_path('client_ready_prd.docx')}")


if __name__ == "__main__":
    main()