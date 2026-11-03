"""CLI entrypoint for the Scope Document Automation pipeline.

Usage:
  python main.py run --transcripts t1.txt t2.txt t3.txt --requirement req.txt
  python main.py run --from-stage 6 --case-id <case_id>
"""
import argparse
import os
import sys

from adapters.metadata_file_adapter import MetadataFileAdapter
from adapters.zoho_metadata_exporter import ZohoMetadataExporter
from pipeline import (
    stage1_intake,
    stage2_parsing,
    stage3_transcript_analysis,
    stage3_reconciliation,
    stage4_decomposition,
    stage5_data_needs,
    stage6_sql_discovery,
    stage7_validation_workbook,
    stage8_human_validation,
    stage9_gap_analysis,
    stage10_scope_generation,
    stage11_acceptance,
)
from pipeline.case_store import CaseStore
from pipeline.claude_client import ClaudeClient
from pipeline.mock_claude_client import MockClaudeClient
from pipeline.unattended import (
    OfflineRulebookClient,
    answer_transcript_questions,
    automated_schema,
    fill_validation_workbook,
)
from pipeline.models import (
    CaseContext,
    DataNeedSpecification,
    GapAnalysis,
    RequirementBaseline,
    RequirementDecomposition,
    RulebookRetrievalResult,
    SQLDiscovery,
    HumanValidationResult,
    TranscriptAnalysis,
)

STAGE_LABELS = {
    2: "Document Parsing",
    3: "Transcript Analysis & Upfront Clarification",
    4: "Requirement Reconciliation",
    5: "Requirement Decomposition",
    6: "Data Need Specification",
    7: "Customer Workspace Metadata Mapping & Query Design",
    8: "Excel Human Validation Workbook Generation",
    9: "Human Validation Workbook Import",
    10: "Gap & Clarification Analysis",
    11: "PRD Draft Generation",
    12: "Human Acceptance",
}


def _load_or_none(store, stage_num, model_cls):
    return store.load_stage(stage_num, model_cls) if store.has_stage(stage_num) else None


def _announce(stage_num: int) -> None:
    print(f"[Stage {stage_num}] {STAGE_LABELS[stage_num]}...")


def run_pipeline(args: argparse.Namespace) -> None:
    from_stage, to_stage = args.from_stage, args.to_stage

    if from_stage <= 1:
        if not args.transcripts:
            sys.exit("--transcripts (at least 1 file) is required when running from stage 1")
        case_id, store = stage1_intake.create_case(
            args.transcripts, args.requirement, base_dir=args.cases_dir
        )
        print(f"[Stage 1] Created case: {case_id}")
    else:
        if not args.case_id:
            sys.exit("--case-id is required when using --from-stage > 1")
        case_id = args.case_id
        store = CaseStore(case_id, base_dir=args.cases_dir)
        if not store.case_dir.exists():
            sys.exit(f"Case '{case_id}' not found under {args.cases_dir}/")
        print(f"[Resume] Using existing case: {case_id}")

    claude_holder: dict = {}

    def claude():
        if "client" not in claude_holder:
            if args.mock:
                print("[Mock mode] Using local heuristic client - no API key/network required.")
                claude_holder["client"] = MockClaudeClient()
            else:
                claude_holder["client"] = ClaudeClient()
        return claude_holder["client"]

    context = _load_or_none(store, 2, CaseContext)
    transcript_analysis = _load_or_none(store, 3, TranscriptAnalysis)
    baseline = _load_or_none(store, 4, RequirementBaseline)
    decomposition = _load_or_none(store, 5, RequirementDecomposition)
    data_needs = _load_or_none(store, 6, DataNeedSpecification)
    retrieval = _load_or_none(store, 65, RulebookRetrievalResult)
    sql_discovery = _load_or_none(store, 7, SQLDiscovery)
    validation = _load_or_none(store, 8, HumanValidationResult)
    gap_analysis = _load_or_none(store, 10, GapAnalysis)

    if from_stage <= 2 <= to_stage:
        _announce(2)
        context = stage2_parsing.run(store)

    if from_stage <= 3 <= to_stage:
        _announce(3)
        transcript_analysis = stage3_transcript_analysis.run(store, claude(), context)
        if args.unattended:
            transcript_analysis = answer_transcript_questions(store, transcript_analysis)
        print(f"Transcript analysis report created: {store.case_dir / 'transcript_analysis_report.md'}")
        if to_stage == 3 and not args.unattended:
            print("Review and clarify the questions, then resume with --from-stage 4 --case-id <case_id>.")
            return

    if from_stage <= 4 <= to_stage:
        _announce(4)
        baseline = stage3_reconciliation.run(store, claude(), context, transcript_analysis)

    if from_stage <= 5 <= to_stage:
        _announce(5)
        decomposition = stage4_decomposition.run(store, claude(), baseline)

    if from_stage <= 6 <= to_stage:
        _announce(6)
        from pipeline.rag_mcp_client import RAGMCPClient

        rag = (
            OfflineRulebookClient()
            if args.unattended and args.mock and not args.rag_url
            else RAGMCPClient(args.rag_url)
        )
        data_needs = stage5_data_needs.run(store, claude(), decomposition, context, rag)
        retrieval = store.load_stage(65, RulebookRetrievalResult)

    if from_stage <= 7 <= to_stage:
        _announce(7)
        if args.skip_metadata:
            print("[Metadata skipped] Validation queries will be answered from the customer validation workbook.")
            schema = {}
        elif args.metadata:
            schema = MetadataFileAdapter(args.metadata).as_schema()
        elif args.metadata_source in ("auto", "rest") and (
            args.metadata_source == "rest"
            or (
                os.getenv("ANALYTICS_ORG_ID")
                and (
                    os.getenv("ANALYTICS_REFRESH_TOKEN")
                    or os.getenv("ANALYTICS_ACCESS_TOKEN")
                )
            )
        ):
            if not args.workspace_id:
                sys.exit(
                    "--workspace-id is required for REST metadata discovery. "
                    "Provide the client workspace ID for this case."
                )
            metadata_path = store.case_dir / "zoho_metadata.json"
            exporter = ZohoMetadataExporter(workspace_id=args.workspace_id)
            exporter.export(str(metadata_path))
            schema = MetadataFileAdapter(str(metadata_path)).as_schema()
            print(f"Zoho REST metadata exported to: {metadata_path}")
        elif args.unattended and args.mock and not args.workspace:
            schema = automated_schema(data_needs)
        else:
            if not args.workspace:
                sys.exit("--workspace is required for stage 7 so metadata can be discovered through Zoho Analytics MCP.")
            from adapters.live_analytics_mcp_adapter import LiveAnalyticsMCPAdapter

            metadata = LiveAnalyticsMCPAdapter(args.workspace, store, args.analytics_mcp_url)
            schema = metadata.as_schema()
        sql_discovery = stage6_sql_discovery.run(store, claude(), data_needs, schema)

    if from_stage <= 8 <= to_stage:
        _announce(8)
        workbook_path = stage7_validation_workbook.run(
            store, decomposition, data_needs, sql_discovery, retrieval, transcript_analysis
        )
        if args.unattended:
            fill_validation_workbook(store)
        print(f"Human validation workbook created: {workbook_path}")
        if to_stage == 8 and not args.unattended:
            print("Complete the workbook, then resume with --from-stage 9 --case-id <case_id>.")

    if from_stage <= 9 <= to_stage:
        _announce(9)
        validation = stage8_human_validation.run(store)

    if from_stage <= 10 <= to_stage:
        _announce(10)
        gap_analysis = stage9_gap_analysis.run(store, claude(), validation, decomposition, data_needs)
        workbook_path = stage7_validation_workbook.append_gap_questions(store, gap_analysis)
        if args.unattended:
            fill_validation_workbook(store)
        print(f"Gap questions added to: {workbook_path}")
        if to_stage > 10 and not args.unattended:
            print("Answer the gap questions in the workbook, then resume with --from-stage 11 --case-id <case_id>.")
            return

    if from_stage <= 11 <= to_stage:
        _announce(11)
        stage10_scope_generation.run(store, claude(), baseline, decomposition, data_needs, validation, gap_analysis)
        final_prd = store.case_dir / "final_prd.md"
        final_prd.write_text(
            (store.case_dir / "prd_draft.md").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    if from_stage <= 12 <= to_stage:
        _announce(12)
        if args.unattended:
            store.save_feedback({
                "accepted": True,
                "notes": "Automatically accepted for unattended generation; customer review remains outstanding.",
            })
        else:
            stage11_acceptance.run(store)

    print(f"\nDone. Case artifacts under: {store.case_dir}")
    if args.unattended:
        print("Three requested outputs:")
        print(f"1. Questions analyser: {store.case_dir / 'transcript_analysis_report.md'}")
        print(f"2. Validation book: {store.case_dir / 'validation_workbook.xlsx'}")
        print(f"3. Final PRD: {store.case_dir / 'final_prd.md'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scope Document Automation pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run the pipeline end-to-end or from a specific stage")
    run_p.add_argument("--transcripts", nargs="+", metavar="T", help="Paths to one or more transcript files")
    run_p.add_argument("--requirement", help="Path to an optional requirement document")
    run_p.add_argument("--rag-url", help="RAG MCP SSE endpoint (defaults to RAG_MCP_URL)")
    run_p.add_argument("--workspace", help="Exact Zoho Analytics workspace name")
    run_p.add_argument(
        "--metadata",
        help="Optional exported Zoho Analytics metadata JSON; avoids live workspace discovery",
    )
    run_p.add_argument(
        "--metadata-source",
        choices=("auto", "rest", "mcp"),
        default="auto",
        help="Metadata source: auto uses REST when Zoho OAuth env vars are configured; otherwise MCP",
    )
    run_p.add_argument(
        "--workspace-id",
        help="Client Zoho Analytics workspace ID for this case (required for REST metadata)",
    )
    run_p.add_argument("--analytics-mcp-url", help="Zoho Analytics MCP SSE endpoint (defaults to ANALYTICS_MCP_URL)")
    run_p.add_argument("--case-id", help="Existing case id (required when --from-stage > 1)")
    run_p.add_argument("--from-stage", type=int, default=1, help="Stage number to start from (1-12)")
    run_p.add_argument("--to-stage", type=int, default=12, help="Stage number to stop after (1-12)")
    run_p.add_argument("--cases-dir", default="cases", help="Base directory for case folders")
    run_p.add_argument(
        "--mock", action="store_true",
        help="Use a local offline heuristic mock instead of the real Claude API (no API key needed)",
    )
    run_p.add_argument(
        "--unattended", action="store_true",
        help="Complete clarification, validation, and acceptance automatically using explicit assumptions",
    )
    run_p.add_argument(
        "--skip-metadata", action="store_true",
        help="Skip Zoho workspace metadata discovery and use the customer validation workbook instead",
    )

    export_p = sub.add_parser("export-metadata", help="Export the complete read-only Zoho Analytics metadata catalog")
    export_p.add_argument(
        "--org-id",
        help="Zoho Analytics organization id; defaults to ANALYTICS_ORG_ID in .env",
    )
    export_p.add_argument("--output", required=True, help="Output JSON path")
    export_p.add_argument(
        "--workspace-id",
        help="Workspace ID to export; required for client-isolated exports",
    )
    export_p.add_argument("--access-token", help="Existing OAuth access token; otherwise refresh-token env vars are used")
    export_p.add_argument(
        "--analytics-url",
        help="Zoho Analytics server URI; defaults to ANALYTICS_SERVER_URL or the .com data center",
    )
    export_p.add_argument(
        "--accounts-url",
        help="Zoho Accounts server URI; defaults to ACCOUNTS_SERVER_URL or the .com data center",
    )

    status_p = sub.add_parser("knowledge-status", help="Check the external RAG knowledge base")
    status_p.add_argument("--rag-url", help="RAG MCP SSE endpoint (defaults to RAG_MCP_URL)")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "run":
        run_pipeline(args)
    elif args.command == "export-metadata":
        from adapters.zoho_metadata_exporter import ZohoMetadataExporter

        output = ZohoMetadataExporter(
            org_id=args.org_id,
            access_token=args.access_token,
            workspace_id=args.workspace_id,
            analytics_url=args.analytics_url,
            accounts_url=args.accounts_url,
        ).export(args.output)
        print(f"Metadata exported to: {output}")
    elif args.command == "knowledge-status":
        from pipeline.rag_mcp_client import RAGMCPClient

        print(RAGMCPClient(args.rag_url).status_sync())


if __name__ == "__main__":
    main()
