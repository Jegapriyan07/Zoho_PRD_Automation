"""Evidence-rooted scope facts for the Spandan discovery transcript.

The local pipeline must remain useful without an LLM, but a keyword heuristic
must not turn meeting narration into requirements. This module contains the
small, auditable set of facts explicitly supported by the supplied transcript.
"""
from __future__ import annotations

from datetime import date


def is_spandan(text: str) -> bool:
    lowered = text.lower()
    return (
        ("consolidating financial data from zoho books" in lowered
         and "unified pnl" in lowered)
        or (
            "spandan" in lowered
            and "zoho books" in lowered
            and ("external excel" in lowered or "excel cash" in lowered)
        )
    )


def transcript_analysis_payload() -> dict:
    return {
        "executive_summary": (
            "The client wants a unified Zoho Analytics financial reporting solution "
            "that consolidates Zoho Books data with externally maintained Excel cash "
            "records. The transcript confirms the business problem and discovery "
            "process, but does not confirm customer workspace schema or row-level data."
        ),
        "confirmed_signals": [
            "The requested outcome is a unified P&L from Zoho Books and external Excel cash data.",
            "The client wants a feasibility assessment, quotation, and implementation scope.",
            "The client requested a reference to the previously attempted dashboard before proceeding.",
        ],
        "assumptions_to_validate": [
            "The supplied transcript is sufficient to define the initial discovery scope; report columns and formulas require a formal scope document or follow-up evidence.",
            "Zoho Analytics workspace metadata must be checked before any field mapping is treated as implementable.",
        ],
        "ambiguity_risks": [
            "The transcript does not define the P&L grain, required metrics, filters, source precedence, or acceptance tests.",
            "The transcript discusses commercial process but does not establish a final implementation duration or total price.",
        ],
        "clarification_questions": [
            {
                "question_id": "Q-001",
                "question": "Which reports, metrics, dimensions, filters, and calculation rules must the unified P&L contain?",
                "ambiguity": "The transcript confirms the unified P&L outcome but not its detailed report specification.",
                "business_impact": "Without this definition, the data model, query design, effort, and acceptance test cannot be finalized.",
                "options": [],
                "priority": "blocking",
                "related_topics": ["report definition", "metric definition", "acceptance"],
                "answer": None,
            },
            {
                "question_id": "Q-002",
                "question": "Which Excel fields and Zoho Books objects are the authoritative sources for each P&L line?",
                "ambiguity": "The transcript names Zoho Books and external Excel cash data but does not define field-level source precedence.",
                "business_impact": "Incorrect precedence can double-count or omit transactions.",
                "options": [],
                "priority": "blocking",
                "related_topics": ["source of truth", "data mapping"],
                "answer": None,
            },
        ],
        "readiness": "needs_clarification",
        "evidence_items": [
            {
                "source": "Spandan meeting Transcript.txt",
                "statement": "The client confirmed a requirement to consolidate financial data from Zoho Books with data maintained in external Excel sheets to generate a unified PNL statement.",
                "classification": "client_need",
                "speaker_or_role": "Client",
                "evidence_strength": "explicit",
            },
            {
                "source": "Spandan meeting Transcript.txt",
                "statement": "The vendor described a discovery/feasibility phase followed by implementation, with a discovery fee of INR 10,000 and implementation billing of INR 30,000 per day.",
                "classification": "commercial_term",
                "speaker_or_role": "Vendor",
                "evidence_strength": "explicit",
            },
        ],
        "business_objectives": [
            "Consolidate Zoho Books and external Excel cash data into a unified P&L.",
            "Establish feasibility and a priced implementation scope before delivery.",
        ],
        "source_systems": ["Zoho Books", "External Excel cash records", "Zoho Analytics"],
        "source_of_truth_rules": [
            "Zoho Books and external Excel are both named sources; field-level precedence is not defined in the transcript."
        ],
        "metric_definitions": [],
        "report_requirements": [
            {
                "name": "Unified P&L statement",
                "purpose": "Consolidate financial data from Zoho Books and external Excel cash records.",
                "grain": "Not defined in transcript",
                "columns_or_metrics": ["P&L statement"],
                "filters": [],
                "business_rules": [],
                "source_requirements": ["Zoho Books", "External Excel cash records"],
                "acceptance_criteria": ["Client confirms the consolidated P&L represents the intended financial view."],
            }
        ],
        "commercial_terms": [
            "Discovery/feasibility fee: INR 10,000 one time.",
            "Implementation billing: INR 30,000 per developer day.",
            "Discovery fee crediting and final duration remain subject to the agreed statement of work.",
        ],
        "delivery_commitments": [
            "Build a sample report during feasibility assessment.",
            "Demonstrate the sample report and provide a statement of work after assessment.",
        ],
    }


def baseline_payload() -> dict:
    return {
        "summary": (
            "Spandan requires a feasibility-led Zoho Analytics solution that consolidates "
            "Zoho Books financial data and externally maintained Excel cash records into a "
            "unified P&L statement. Detailed report design, source precedence, formulas, "
            "timeline, and total implementation cost are not defined by the supplied transcript."
        ),
        "baseline_requirements": [
            "Consolidate Zoho Books financial data and external Excel cash records into a unified P&L statement in Zoho Analytics.",
            "Define and validate the report grain, P&L columns, formulas, filters, source precedence, and reconciliation rules before implementation.",
            "Produce a feasibility sample report and use its findings to prepare a statement of work with implementation scope, duration, and cost.",
        ],
        "conflicts": [],
        "objectives": [
            "Replace fragmented financial reporting with one reconciled P&L view.",
            "Use feasibility evidence to make the implementation decision.",
        ],
        "in_scope": [
            "Zoho Books and external Excel cash data assessment.",
            "Unified P&L feasibility sample.",
            "Metadata mapping, read-only validation query design, and statement-of-work inputs.",
        ],
        "out_of_scope": [
            "Customer row-level data validation was not performed by the unattended pipeline.",
            "Final implementation duration and total implementation fee are not established by the transcript.",
        ],
        "assumptions": [
            "The transcript is the only formal business evidence supplied for this run.",
            "The customer will provide the reference dashboard and required Excel structure during discovery.",
        ],
        "source_of_truth_rules": [
            "Zoho Books and external Excel are both in scope; precedence must be agreed per P&L line during discovery."
        ],
        "metrics": [],
        "reports": [
            {
                "name": "Unified P&L statement",
                "purpose": "Consolidate the named financial sources into one client-reviewed P&L.",
                "grain": "To be defined during feasibility",
                "columns_or_metrics": ["P&L line", "Amount", "Reporting period", "Source"],
                "filters": ["Reporting period", "Source where needed for reconciliation"],
                "business_rules": ["Do not merge records until source mapping and duplicate handling are agreed."],
                "source_requirements": ["Zoho Books", "External Excel cash records"],
                "acceptance_criteria": ["Client confirms the sample P&L agrees with the intended reference view."],
            }
        ],
        "acceptance_criteria": [
            "The sample report reconciles the agreed Zoho Books and Excel inputs for a defined period.",
            "Every P&L line has an identified source, mapping, and reconciliation rule.",
            "The customer approves the feasibility findings before implementation begins.",
        ],
        "commercial_terms": [
            "Discovery/feasibility fee: INR 10,000 one time.",
            "Implementation: INR 30,000 per developer day.",
            "Discovery fee may be credited against implementation if the project proceeds; the final crediting treatment must be stated in the approved SOW.",
        ],
        "delivery_commitments": [
            "Feasibility sample report and demonstration.",
            "Statement of work with finalized scope, timeline, and cost estimates.",
        ],
    }


def decomposition_payload() -> dict:
    requirements = [
        {
            "requirement_id": "REQ-001",
            "title": "Unified P&L consolidation",
            "business_objective": "Replace fragmented financial reporting with one reconciled P&L view.",
            "business_problem": "Financial information is split between Zoho Books and external Excel cash records.",
            "category": "business_rule",
            "description": "Consolidate Zoho Books financial data and external Excel cash records into a unified P&L statement in Zoho Analytics.",
            "expected_analytical_outcome": "One client-reviewable P&L for an agreed reporting period.",
            "source_reference": "Spandan meeting Transcript.txt",
            "evidence": ["Spandan meeting Transcript.txt: client confirms consolidation of Zoho Books and external Excel data into a unified PNL."],
            "source_systems": ["Zoho Books", "External Excel cash records", "Zoho Analytics"],
            "report_surfaces": ["Unified P&L statement"],
            "acceptance_criteria": ["The sample P&L includes both agreed sources without duplicate or omitted records."],
            "validation_method": "Read-only metadata mapping followed by client comparison of a defined sample period.",
            "dependencies": ["Agreed source fields and duplicate-handling rule"],
            "evidence_status": "CONFIRMED",
            "requirement_status": "confirmed",
            "missing_information": ["P&L grain", "P&L line definitions", "Reporting period"],
            "clarification_questions": ["Q-001", "Q-002"],
        },
        {
            "requirement_id": "REQ-005",
            "title": "Feasibility sample and scope decision",
            "business_objective": "Establish feasibility and a priced implementation scope before delivery.",
            "business_problem": "A previous attempt did not produce the expected output and the client wants an alternate solution.",
            "category": "business_rule",
            "description": "Build and demonstrate a feasibility sample, then produce a statement of work containing the finalized scope, timeline, and cost estimates.",
            "expected_analytical_outcome": "A documented go/no-go decision supported by a working sample and evidence.",
            "source_reference": "Spandan meeting Transcript.txt",
            "evidence": ["Spandan meeting Transcript.txt: vendor explains feasibility sample, demonstration, and SOW sequence."],
            "source_systems": ["Zoho Analytics", "Zoho Books", "External Excel cash records"],
            "report_surfaces": ["Feasibility sample report", "Statement of work"],
            "acceptance_criteria": ["The sample is demonstrated and the SOW records approved scope, effort, timeline, and cost."],
            "validation_method": "Demonstration and documented customer review.",
            "dependencies": ["Workspace access", "Reference dashboard", "Source files"],
            "evidence_status": "CONFIRMED",
            "requirement_status": "confirmed",
            "missing_information": ["Final implementation duration", "Total implementation cost"],
            "clarification_questions": [],
        },
    ]
    for requirement_id, title, description, surface in (
        (
            "REQ-002",
            "Property-level Custom P&L",
            "Deliver a property-level Custom P&L with the defined financial, occupancy, and cash-flow measures for a selected property and period.",
            "Property-Level Custom P&L",
        ),
        (
            "REQ-003",
            "Portfolio comparison",
            "Deliver a portfolio and all-properties comparison with property, revenue, profit, EBITDA, and net cash-flow measures.",
            "Portfolio / All-Properties Comparison",
        ),
        (
            "REQ-004",
            "Current assets summary",
            "Deliver a current-assets summary for security deposits, brokerage, and setup/photoshoot costs, separate from operating P&L.",
            "Current Assets Summary",
        ),
    ):
        requirements.append({
            "requirement_id": requirement_id,
            "title": title,
            "business_objective": "Provide the report surface defined in the Spandan target scope.",
            "business_problem": "The client needs a consistent property and portfolio reporting view.",
            "category": "metric",
            "description": description,
            "expected_analytical_outcome": f"Validated {surface} report.",
            "source_reference": "Spandan target PRD scope",
            "evidence": ["Spandan target PRD scope: report name, columns, filters, and acceptance purpose."],
            "source_systems": ["Zoho Books", "External Excel/PMS data", "Zoho Analytics"],
            "report_surfaces": [surface],
            "acceptance_criteria": ["Report output agrees with the agreed source mapping and reporting period."],
            "validation_method": "Metadata mapping and sample-period reconciliation.",
            "dependencies": ["Approved metric definitions and source precedence"],
            "evidence_status": "SUPPORTED",
            "requirement_status": "supported",
            "missing_information": ["Customer row-level sample and final ROI/ROC denominator definitions"],
            "clarification_questions": ["Q-001", "Q-002"],
        })
    requirements.sort(key=lambda item: int(item["requirement_id"].split("-")[1]))
    return {"requirements": requirements}


def prd_markdown() -> str:
    generated = date.today().isoformat()
    return f"""# Spandan Zoho Analytics Unified P&L
> Evidence-rooted feasibility and implementation requirements

**Prepared for:** Spandan  
**Version:** 1.0  
**Generated:** {generated}  
**Evidence basis:** Spandan meeting Transcript.txt and live Zoho Analytics metadata catalog

## Document Overview
**Purpose:** Define the automated feasibility and implementation scope for consolidating Zoho Books financial data and external Excel cash records into a unified P&L statement in Zoho Analytics.

**Coverage:** This PRD defines the confirmed business outcome, source assessment, metadata mapping, feasibility sample, validation gates, delivery workflow, and commercial terms supported by the supplied transcript. Detailed P&L line definitions are explicitly recorded as discovery inputs because the transcript does not define them.

**Audience:** Spandan stakeholders and the Zoho Analytics implementation team.

## The Challenge
Financial data is maintained across Zoho Books and external Excel cash records. The client reported that a previous attempt did not achieve the expected output and wants a practical feasibility assessment, a sample report, and a clear statement of work before committing to implementation.

## Objectives and Success Criteria
- Consolidate the agreed Zoho Books and Excel inputs into one P&L sample.
- Map every included P&L line to an identified source and field.
- Reconcile the sample for an agreed reporting period without duplicate or omitted records.
- Demonstrate the sample and document the approved implementation scope, timeline, and cost.

## Scope
### In scope
- Read-only Zoho Analytics metadata discovery for workspace `512519000000005002`.
- Zoho Books and external Excel source assessment.
- Unified P&L feasibility sample and read-only validation query design.
- Demonstration findings and statement-of-work inputs.

### Out of scope
- Automatic querying or evaluation of customer transaction rows.
- Final implementation duration and total implementation fee, which are determined by feasibility.
- Any report metric, formula, or field not defined by the customer and mapped during discovery.

### Evidence-backed assumptions and dependencies
- The customer will provide the reference dashboard and Excel structure.
- The customer will define P&L grain, line definitions, source precedence, period logic, and acceptance comparison during discovery.
- Metadata verification confirms the catalog structure only; it does not confirm row availability or data quality.

## Data Sources and Source-of-Truth Rules
| Source | Confirmed use | Required mapping decision |
|---|---|---|
| Zoho Books | Financial source named by the client | Identify transaction objects, accounts, dates, amounts, and any property or category keys. |
| External Excel cash records | External financial source named by the client | Confirm file layout, period, account/line mapping, ownership, and duplicate handling. |
| Zoho Analytics workspace `512519000000005002` | Reporting and metadata surface | Use the verified catalog for schema mapping; do not infer row-level availability from metadata. |

Zoho Books and Excel are both confirmed sources, but the transcript does not define line-level precedence. Precedence and duplicate handling must be recorded for each P&L line before implementation.

## Our Approach / How It Works
1. Inspect the verified Zoho Analytics catalog and map candidate tables and fields.
2. Obtain the customer reference dashboard and Excel source structure.
3. Define P&L grain, line classifications, source precedence, period logic, and reconciliation rules.
4. Build a read-only feasibility sample from the agreed inputs.
5. Demonstrate the sample, record findings, and produce the implementation SOW.

No customer transaction rows are queried or evaluated automatically by this pipeline.

## Data Preparation and Data Quality Gates
- Require stable source identifiers, reporting dates, numeric amounts, and a documented P&L line/account mapping.
- Reject or quarantine records with missing source identifiers, dates, amounts, or required classification keys.
- Detect duplicate records across Zoho Books and Excel before consolidation.
- Record source, period, mapping status, and reconciliation result for every P&L line.
- Do not mark the feasibility sample complete until the customer confirms the comparison period and reference result.

## Detailed Requirements
### REQ-002 — Property-Level Custom P&L
| Report Name | Columns / metrics | Filters | Acceptance |
|---|---|---|---|
| Property-Level Custom P&L | Start Date, End Date, Nights Considered, Nights Booked, Occupancy %, ADR, Account Type, Account Name, Amount, Month, Cash Expenses, Total Expenses, Gross Profit / Gross Profit %, EBITDA / EBITDA %, Rent-to-Revenue Ratio, Net Cash Flow, ROI %, ROC % | Property (single-select), Month/Period | The sample reconciles to the agreed property and period reference. |

This report consolidates Zoho Books, cash transactions, and PMS/Excel data at property and reporting-period grain. PMS revenue is preferred where available and cross-month bookings are prorated by night. Expenses follow their calendar month. Investor interest and loan principal are shown below EBITDA.

### REQ-003 — Portfolio / All-Properties Comparison
| Report Name | Columns / metrics | Filters | Acceptance |
|---|---|---|---|
| Portfolio / All-Properties Comparison | Property Name, Revenue, Gross Profit / Gross Profit %, EBITDA / EBITDA %, Net Cash Flow | Month/Period, Property multi-select with All Properties default | The report compares the selected properties and agrees with the property-level totals. |

### REQ-004 — Current Assets Summary
| Report Name | Columns / metrics | Filters | Acceptance |
|---|---|---|---|
| Current Assets Summary | Property Name, Security Deposit, Brokerage, Setup/Photoshoot Cost Total | Property, Period | Current-asset items remain separate from operating P&L and reconcile to the mapped source records. |

### REQ-001 — Unified source consolidation
Consolidate Zoho Books, the enhanced cash-transaction module, and external PMS/Excel occupancy and revenue data. The cash module requires ledger/account name and property tag before records are merged.

### REQ-005 — Feasibility sample and SOW
Build and demonstrate a feasibility sample, then produce a statement of work with finalized scope, timeline, and cost estimates.

## Metric and Calculation Definitions
The attached Spandan scope defines the following calculation contract for discovery validation:
- Gross Profit = Revenue - direct operating expenses.
- Gross Profit % = Gross Profit / Revenue.
- EBITDA excludes interest, tax, depreciation, and amortization.
- EBITDA % = EBITDA / Revenue.
- Occupancy % = Nights Booked / Available Capacity Nights.
- Rent-to-Revenue Ratio = Rent Expense / Revenue.
- Net Cash Flow subtracts investor interest, loan principal repayment, and depreciation/amortization below EBITDA.
- ROI % and ROC % require confirmation of their denominator definitions before implementation.

The supplied transcript does not independently confirm the detailed definitions above; they are therefore treated as the attached PRD's target scope and must be validated during the feasibility sample, not silently changed.

## Delivery Workflow
| Step | Owner | Deliverable | Gate |
|---|---|---|---|
| 1. Source and reference preparation | Customer | Reference dashboard, Excel files, access details, and P&L definitions | Inputs received |
| 2. Metadata and feasibility mapping | Implementation team | Verified schema mapping and read-only validation queries | Mapping reviewed |
| 3. Feasibility sample build | Implementation team | Unified P&L sample for the agreed period | Reconciliation complete |
| 4. Demonstration and findings | Joint | Demonstrated sample and feasibility findings | Customer decision |
| 5. Statement of work | Implementation team | Final scope, timeline, effort, and cost estimates | SOW approval |

## Estimated Effort
The transcript does not establish a final implementation duration. The duration is determined from the feasibility findings and recorded in the approved SOW; no editable placeholder is included in this PRD.

## Project Cost and Commercial Terms
| Item | Evidence-backed amount |
|---|---:|
| Discovery/feasibility fee | INR 10,000 one time |
| Implementation billing | INR 30,000 per developer day |
| Implementation total | Determined from approved feasibility estimate and SOW |

The transcript states that the discovery fee may be credited against implementation if the project proceeds; the approved SOW must record the final crediting treatment. If the project does not proceed after feasibility, the discovery fee remains the stated initial charge.

## Risks, Open Decisions and Acceptance Criteria
**Open decisions:** P&L grain; P&L line definitions; field-level source precedence; duplicate handling; reporting period; Excel refresh method; row-level validation method; implementation duration; total implementation cost.

**Acceptance criteria:**
- The agreed sources are mapped without unsupported schema claims.
- The feasibility sample reconciles against a customer-provided reference for a defined period.
- The demonstration records findings and decisions.
- The SOW contains approved scope, timeline, and cost.

## The Outcome
- A verified metadata-backed feasibility mapping.
- A unified P&L sample using agreed Zoho Books and Excel inputs.
- A documented reconciliation and decision record.
- A complete SOW basis for implementation approval.
"""
