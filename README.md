# Zoho PRD Automation

Zoho PRD Automation converts meeting evidence into validated analytics requirements and a client-ready product requirements document (PRD).

The pipeline combines transcript analysis, requirement reconciliation, Zoho Finance knowledge retrieval, Zoho Analytics metadata discovery, and a human-owned Excel validation step. It generates read-only validation queries and does not automatically query or evaluate original customer data.

## What it does

1. Creates a case from one or more meeting transcripts.
2. Parses and normalizes the evidence.
3. Identifies confirmed signals, assumptions, risks, and clarification questions.
4. Reconciles transcripts with an optional requirements document.
5. Decomposes the baseline into atomic, testable requirements.
6. Retrieves supporting Zoho Finance definitions through the RAG MCP service.
7. Maps conceptual data needs to Zoho Analytics metadata and designs read-only queries.
8. Generates an Excel validation workbook for human review.
9. Imports human validation results and analyzes gaps.
10. Generates a PRD in Markdown and Word formats.
11. Records the final acceptance decision and feedback.

See [PROJECT_WORKFLOW.md](PROJECT_WORKFLOW.md) for the complete stage-by-stage workflow and handoffs.

## Requirements

- Python 3.11 or newer
- Access to the Claude API for live reasoning, or `--mock` for offline local execution
- RAG MCP service for data-definition retrieval when running stages 6 and later
- Zoho Analytics MCP service and workspace access when running metadata discovery

Install dependencies:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

## Configuration

Copy the example environment file and fill in the values for your environment:

```powershell
Copy-Item .env.example .env
```

Never commit `.env` or real API credentials. The committed example contains placeholders only.

Important settings include:

- `ANTHROPIC_API_KEY`: Claude API key for live reasoning.
- `RAG_MCP_URL`: RAG MCP SSE endpoint.
- `ANALYTICS_MCP_URL`: Zoho Analytics MCP SSE endpoint, when applicable.
- Zoho Analytics OAuth settings in `.env.example`.

## Usage

Run the complete pipeline with live services:

```powershell
py main.py run `
  --transcripts transcript.txt `
  --requirement requirement.txt `
  --workspace "Customer Analytics"
```

Run locally without the Claude API:

```powershell
py main.py run --transcripts transcript.txt --mock
```

Run fully unattended and produce the questions analyser, validation workbook,
and final PRD without manual workbook edits:

```powershell
py main.py run --transcripts transcript.txt --mock --unattended
```

In unattended mock mode, missing live RAG and Analytics services are replaced
with explicit synthetic/assumption-based outputs. Those assumptions are marked
in the generated artifacts and are not customer-data validation.

Resume an existing case from a later stage:

```powershell
py main.py run --from-stage 4 --case-id <case-id>
```

The default case output directory is `cases/`. Local case artifacts and customer evidence are intentionally ignored by Git.
Unattended runs print exactly three primary output paths: the questions analyser,
the validation workbook, and `final_prd.md`.

## Project layout

```text
main.py                 CLI entry point
pipeline/               Pipeline stages, models, clients, and renderers
adapters/               Zoho Analytics and metadata adapters
sample_case/            Example input/output material
docs/                   Supporting documentation
PROJECT_WORKFLOW.md     Detailed workflow and stage handoffs
requirements.txt        Python dependencies
```

## Safety and data handling

- Metadata discovery and query generation are read-only.
- Human validation is required before PRD generation.
- Customer transcripts, credentials, workbooks, and generated case artifacts should remain local.
- Review `.gitignore` before publishing any additional files.
