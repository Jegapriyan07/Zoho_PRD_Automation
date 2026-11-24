# Zoho PRD Automation

Zoho PRD Automation converts meeting evidence into validated analytics requirements and a client-ready product requirements document (PRD).

The pipeline combines transcript analysis, requirement reconciliation, Zoho Finance knowledge retrieval, Zoho Analytics metadata discovery, and a human-owned Excel validation step. It generates read-only validation queries and does not automatically query or evaluate original customer data.

## What it does

1. Creates a case from one or more meeting transcripts.
2. Parses and normalizes the evidence.
3. Uses AI to identify confirmed signals, assumptions, risks, and clarification questions.
4. Stops for stakeholder answers to transcript clarification questions before proceeding.
5. Reconciles transcripts with an optional requirements document after the clarification gate.
6. Decomposes the baseline into atomic, testable requirements.
7. Retrieves supporting Zoho knowledge-base definitions through the RAG MCP service, targeted at exactly one knowledge base (e.g. `finance` or `recruit`).
8. Maps conceptual data needs to Zoho Analytics metadata and designs read-only queries.
9. Generates an Excel validation workbook for human review.
10. Imports human validation results and analyzes gaps.
11. Persists an internal analytical assessment with evidence, feasibility, mappings, limitations,
    and a prioritized gap register.
12. Generates a PRD in Markdown and Word formats from the assessment and validated inputs.
13. Records the final acceptance decision and feedback.

Stage 3 uses a hierarchical analysis automatically when the combined transcript
size exceeds `TRANSCRIPT_ANALYSIS_CHUNK_CHARS` (default `18000`). It extracts
bounded evidence from transcript chunks, then performs one global consolidation
pass. Chunk candidates are never used as the final requirement list; the
consolidated analysis and saved stakeholder answers are passed to reconciliation.

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
- `RAG_KNOWLEDGE_BASE`: target RAG knowledge base name (e.g. `finance`, `recruit`); overridden by `--rag-kb`.
- `ANALYTICS_MCP_URL`: Zoho Analytics MCP SSE endpoint, when applicable.
- Zoho Analytics OAuth settings in `.env.example`.

### Connect to Zoho Analytics metadata

Create the private local configuration file, then open it in an editor and
replace the four Zoho placeholders with your own values:

```powershell
Copy-Item .env.example .env
notepad .env
```

For OAuth refresh-token access, set `ANALYTICS_CLIENT_ID`,
`ANALYTICS_CLIENT_SECRET`, `ANALYTICS_REFRESH_TOKEN`, and
`ANALYTICS_ORG_ID`. The client secret and refresh token stay in `.env`, which
is ignored by Git. The exporter only reads metadata and never queries
customer data rows.

Workspace IDs are not stored in `.env`, because each client case can use a
different workspace. Pass the client workspace ID with that case's command.
REST discovery passes only that workspace's tables and columns to the existing
metadata mapping stage.

The OAuth consent request must include the `ZohoAnalytics.metadata.read`
scope. After creating the consent URL in the Zoho API Console and receiving
the authorization code, exchange it once without exposing it in chat:

```powershell
py scripts\setup_zoho_oauth.py
```

The script reads the client ID and secret from `.env`, prompts for the code,
and updates only `ANALYTICS_REFRESH_TOKEN`.

To discover the organizations available to the configured OAuth user:

```powershell
py scripts\get_zoho_org.py
```

This prints organization names and IDs only; it never prints the access token,
refresh token, client secret, or client ID. Set the selected ID as
`ANALYTICS_ORG_ID` in `.env` before running metadata discovery.

Export the complete read-only catalog:

```powershell
py main.py export-metadata --workspace-id "51251900000005002" --output cases\zoho_metadata.json
```

You can override the organization ID for a one-off export:

```powershell
py main.py export-metadata --org-id "<organization-id>" --output cases\zoho_metadata.json
```

The export may contain an `errors` list when your OAuth user lacks access to a
specific metadata endpoint; inspect that list before using the catalog.

### Connect to Zoho Recruit metadata

Zoho Recruit uses a separate OAuth client configuration from Zoho Analytics.
Add `ZOHO_RECRUIT_CLIENT_ID`, `ZOHO_RECRUIT_CLIENT_SECRET`, and
`ZOHO_RECRUIT_ACCOUNTS_URL` to `.env`, using the Accounts server for your Zoho
data center. For the EU data center, create the Self Client at
`https://api-console.zoho.eu/` and use `https://accounts.zoho.eu` and
`https://recruit.zoho.eu/recruit/v2`. OAuth client credentials are tied to
their data center; create a new client in the EU console rather than reusing
credentials from another Zoho region. Request both
`ZohoRecruit.settings.modules.read` and `ZohoRecruit.settings.fields.read`
scopes and enable offline access when generating the authorization code. A
module name is not part of OAuth token generation; it is passed later when
requesting that module's metadata.

Exchange the one-time authorization code for a refresh token:

```powershell
py scripts\setup_zoho_recruit_oauth.py
```

The script saves `ZOHO_RECRUIT_REFRESH_TOKEN` to `.env`. Export metadata for
the requested Recruit module API names:

```powershell
py main.py export-recruit-metadata --modules Candidates Contacts --output cases\zoho_recruit_metadata.json
```

If field metadata is accessible but module metadata is not, explicitly export
fields only with your existing refresh token:

```powershell
py main.py export-recruit-metadata --modules Candidates --fields-only --output cases\zoho_recruit_metadata.json
```

This mode never calls the module metadata endpoint. The export marks
`metadata_scope` as `fields-only`, records the limitation, and leaves module
metadata null. Field names and types come from the live fields endpoint;
entity names are the requested module API names. Complete export remains the
default and does not silently fall back to fields only. To use the saved
export in stage 7, pass `--metadata cases\zoho_recruit_metadata.json`.

For an OAuth client that has a registered redirect URI, set
`ZOHO_RECRUIT_REDIRECT_URI` in `.env` or pass `--redirect-uri` to the setup
script; it must exactly match the URI used to generate the authorization code.
Authorization codes expire quickly and can only be exchanged once. If token
setup fails, the script reports Zoho's OAuth error and next steps.

The stage-7 pipeline can use the same live Recruit metadata directly:

```powershell
py main.py run --from-stage 7 --case-id <case-id> --metadata-source recruit --recruit-modules Candidates Contacts
```

The Recruit exporter reads module and field metadata only. It does not retrieve
Recruit records or customer data.

Metadata is never synthesized as customer schema. If no live or exported catalog
is available, mappings and query design are recorded as `UNVERIFIED` with the
explicit limitation `Workspace metadata not available for verification.`.
Unattended/mock runs remain useful for plumbing validation, but they do not prove
customer schema or data availability.

## Usage

Run the complete pipeline with live services:

```powershell
py main.py run `
  --transcripts transcript.txt `
  --requirement requirement.txt `
  --workspace "Customer Analytics"
```

The run pauses after AI transcript analysis if clarification questions remain.
Answer the questions in the generated `transcript_clarifications_<case-id>.json`
file and rerun with `--from-stage 4 --case-id <case-id>`; stages 4 onward cannot
run until every transcript question has an answer. `--unattended` is an explicit
exception that records assumptions instead of stakeholder decisions.

For REST stage-7 mapping, pass `--workspace-id` for the client associated with
that case.

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
with explicit feasibility assumptions. The generated PRD never contains
editable placeholders: unsupported details are recorded as open decisions or
feasibility gates. Those assumptions are not customer-data validation.

The pipeline uses the RAG MCP knowledge base by default, including in mock
reasoning mode. Use `--rag-url` or `RAG_MCP_URL` to select the service. Each
run targets exactly one isolated knowledge base — use `--rag-kb` or
`RAG_KNOWLEDGE_BASE` to pick `finance`, `recruit`, or another knowledge base
registered on the RAG service; it otherwise defaults to `recruit` when
`--metadata-source recruit` is selected, else `finance`. The offline rulebook
fallback is never selected implicitly; use `--offline-rag` only for an
explicitly ungrounded plumbing run.

Resume an existing case from a later stage:

```powershell
py main.py run --from-stage 4 --case-id <case-id>
```

The default case output directory is `cases/`. Local case artifacts and customer evidence are intentionally ignored by Git.
Every generated case-level artifact includes its case ID in the filename, for example
`validation_workbook_case_20261103_184217_b26a86.xlsx`. This prevents Excel and
other applications from confusing outputs from different runs. Unattended runs
print exactly three primary output paths: the questions analyser, the validation
workbook, and the case-specific final PRD.

## Analytics Adviser web UI

A local browser front end for the whole pipeline: select files from your device, watch each stage run live, answer the human-owned steps in the page, and download the generated PRD, Word/PDF files, and validation workbook.

```powershell
py -m analytics_adviser          # opens http://127.0.0.1:8765
```

- **Inputs**: transcripts (required), requirement documents/screenshots and a Zoho metadata JSON export (optional).
- **Modes**: *Guided* pauses for clarification answers, requirement validation, and gap answers (or lets you upload a completed workbook); *Automatic* runs unattended with recorded assumptions.
- **Engine**: *Local offline* (default, no API key or network), *Local Ollama*, or whatever LLM settings are already in `.env`.
- The server runs `main.py` as a local subprocess and streams its output; nothing is sent to a hosted service unless you pick a remote LLM or enable the RAG service. Uploads and results live under `cases/` (Git-ignored).

## Project layout

```text
main.py                 CLI entry point
analytics_adviser/      Local web UI (Flask backend + static front end)
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
