"""Canonical analysis-to-PRD contract learned from the supplied reference case."""

ANALYSIS_RULES = """
REFERENCE-QUALITY ANALYSIS CONTRACT
1. Classify every material statement as client need, client decision, client constraint,
   analyst/vendor explanation, commercial term, implementation dependency, or noise.
2. Preserve evidence at the smallest useful unit: source filename, speaker/role when known,
   and a concise statement. Never promote analyst questions or sales/process language into scope.
3. Build the business model before atomic requirements: source systems, source precedence, grain,
   dimensions, time logic, formulas, exclusions, data-quality gates, and report surfaces.
4. Separate confirmed facts, explicit decisions, supported inferences, assumptions, and unresolved
   questions. An assumption is never presented as a client decision.
5. Every requirement must have an evidence reference, acceptance test, validation method, source
   data need, and report surface or explain why it is non-reporting.
6. Preserve commercial terms and delivery commitments only when explicitly stated; mark amounts,
   duration, and crediting rules as evidence-backed or unresolved.
7. Ask questions only when the answer can change scope, formula, source precedence, data model,
   ownership, acceptance, effort, or cost. Ask one decision per question.
8. The PRD must be a faithful transformation of the finalized baseline and validation evidence:
   no generic filler, invented numbers, invented fields, or silently resolved conflicts.
"""

PRD_STRUCTURE = """
TARGET PRD STRUCTURE
- Title and subtitle
- Document Overview: purpose, coverage, audience, status and evidence basis
- The Challenge: current process, failure/problem, business impact
- Objectives and Success Criteria
- Scope: in scope, out of scope, assumptions, dependencies
- Data Sources and Source-of-Truth Rules
- Our Approach / How It Works
- Data Preparation and Data Quality Gates
- Detailed Requirements:
  1. Property-Level Custom P&L
  2. Portfolio / All-Properties Comparison
  3. Current Assets Summary
  Each report subsection must state report name, grain, columns/metrics, filters,
  formulas/business rules, source mapping, and validation method.
- Metric and Calculation Definitions
- Delivery Workflow: customer preparation, discovery/feasibility, build, testing,
  handover, training and hypercare with owners and evidence
- Estimated Effort
- Project Cost and Commercial Terms
- Risks, Open Decisions and Acceptance Criteria
- The Outcome
"""
