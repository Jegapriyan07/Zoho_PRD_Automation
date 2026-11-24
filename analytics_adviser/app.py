"""Flask backend for Analytics Adviser.

The pipeline runs locally as `main.py` subprocesses. The UI streams their console
output and pauses at the pipeline's human-owned steps (transcript clarifications,
workbook validation, gap answers) so the user answers them in the browser.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory
from openpyxl import load_workbook
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
sys.path.insert(0, str(ROOT))

from pipeline.case_store import CaseStore  # noqa: E402
from pipeline.models import (  # noqa: E402
    TranscriptAnalysis,
    TranscriptClarificationAnswer,
    TranscriptClarificationResponse,
)
from pipeline.stage7_validation_workbook import STATUS_OPTIONS, column_map  # noqa: E402
from pipeline.unattended import (  # noqa: E402
    AUTOMATED_NOTE,
    answer_transcript_questions,
    fill_validation_workbook,
)

TRANSCRIPT_TEXT_EXTS = {".txt", ".md", ".vtt", ".srt", ".log", ".csv"}
REQUIREMENT_EXTS = {".txt", ".md", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
STAGE_RE = re.compile(r"^\[Stage (\d+)\]")
CASE_RE = re.compile(r"Created case: (\S+)")

# (from_stage, to_stage, next step the user must act on)
GUIDED_PHASES = {
    "analyse": (1, 3, "clarify"),
    "build": (4, 8, "validate"),
    "assess": (9, 10, "gaps"),
    "write": (11, 11, "done"),
}


class Job:
    def __init__(self, job_id: str, options: dict, upload_dir: Path, inputs: dict):
        self.id = job_id
        self.options = options
        self.upload_dir = upload_dir
        self.inputs = inputs
        self.case_id: str | None = None
        self.lines: list[dict] = []
        self.status = "running"  # running | waiting | done | error | cancelled
        self.step = "analyse"  # phase running now, or the step the user must act on
        self.phase = "analyse"
        self.process: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.error: str | None = None

    def log(self, text: str, kind: str = "out") -> None:
        with self.lock:
            self.lines.append({"t": time.time(), "text": text, "kind": kind})

    @property
    def store(self) -> CaseStore:
        if not self.case_id:
            abort(409, "Case has not been created yet.")
        return CaseStore(self.case_id, base_dir=str(ROOT / "cases"))


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
    jobs: dict[str, Job] = {}

    def get_job(job_id: str) -> Job:
        job = jobs.get(job_id)
        if not job:
            abort(404, "Unknown job.")
        return job

    # ---- pipeline execution -------------------------------------------------

    def build_command(job: Job, from_stage: int, to_stage: int, auto: bool) -> list[str]:
        opts = job.options
        cmd = [sys.executable, "-u", "main.py", "run", "--cases-dir", "cases",
               "--from-stage", str(from_stage), "--to-stage", str(to_stage)]
        if from_stage <= 1:
            cmd += ["--transcripts", *job.inputs["transcripts"]]
            if job.inputs["requirements"]:
                cmd += ["--requirement", *job.inputs["requirements"]]
        else:
            cmd += ["--case-id", job.case_id]
        if opts["engine"] == "mock":
            cmd.append("--mock")
        if auto:
            cmd.append("--unattended")
        if job.inputs.get("metadata"):
            cmd += ["--metadata", job.inputs["metadata"]]
        else:
            cmd.append("--skip-metadata")
        if opts["use_rag"]:
            cmd += ["--rag-kb", opts["rag_kb"]]
        else:
            cmd.append("--offline-rag")
        return cmd

    def launch(job: Job, phase: str, from_stage: int, to_stage: int, auto: bool = False) -> None:
        job.phase = job.step = phase
        job.status = "running"
        job.error = None
        cmd = build_command(job, from_stage, to_stage, auto)
        job.log(f"$ {' '.join(Path(c).name if i == 0 else c for i, c in enumerate(cmd))}", "cmd")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        if job.options["engine"] == "ollama":
            env["LLM_PROVIDER"] = "ollama"
            if job.options.get("ollama_model"):
                env["LLM_MODEL"] = job.options["ollama_model"]
        if job.options["engine"] != "mock" and job.options.get("headroom", "").isdigit():
            env["LLM_REASONING_HEADROOM"] = job.options["headroom"]
        threading.Thread(
            target=supervise, args=(job, cmd, env, phase, to_stage, auto), daemon=True
        ).start()

    def supervise(job: Job, cmd: list[str], env: dict, phase: str, to_stage: int, auto: bool) -> None:
        try:
            job.process = subprocess.Popen(
                cmd, cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for raw in job.process.stdout:
                text = raw.rstrip("\r\n")
                match = CASE_RE.search(text)
                if match and not job.case_id:
                    job.case_id = match.group(1)
                if text.strip():
                    job.log(text)
            code = job.process.wait()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            job.status, job.error = "error", str(exc)
            job.log(f"Failed to run pipeline: {exc}", "err")
            return
        if job.status == "cancelled":
            return
        if code != 0:
            job.status = "error"
            tail = [line["text"] for line in job.lines[-6:] if line["kind"] == "out"]
            job.error = tail[-1] if tail else f"Pipeline exited with code {code}"
            job.log(f"Pipeline stopped (exit code {code}).", "err")
            return
        advance(job, phase, auto)

    def advance(job: Job, phase: str, auto: bool) -> None:
        if auto:
            finish(job)
            return
        if phase == "analyse":
            job.log("Waiting for your answers to the clarification questions.", "info")
            job.status, job.step = "waiting", "clarify"
        elif phase == "build":
            job.status, job.step = "waiting", "validate"
            job.log("Validation workbook is ready. Review it in the browser.", "info")
        elif phase == "assess":
            if gap_rows(job):
                job.status, job.step = "waiting", "gaps"
                job.log("Follow-up gap questions need your answers.", "info")
            else:
                launch(job, "write", 11, 11)
        elif phase == "write":
            finish(job)

    def finish(job: Job) -> None:
        job.status, job.step = "done", "done"
        job.log("All stages complete. Your PRD is ready.", "info")

    # ---- helpers reading case files -----------------------------------------

    def state_json(job: Job, name: str) -> dict:
        path = job.store.state_dir / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def workbook_path(job: Job) -> Path:
        return job.store.artifact_path("validation_workbook.xlsx")

    def gap_rows(job: Job) -> list[dict]:
        path = workbook_path(job)
        if not path.exists():
            return []
        sheet = load_workbook(path)["Gaps & Clarifications"]
        return [
            {"row": index, "requirement": row[0] or "general", "question": row[1], "answer": row[2] or ""}
            for index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2)
            if row[1] and not row[2]
        ]

    # ---- routes -------------------------------------------------------------

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.post("/api/jobs")
    def create_job():
        transcripts = [f for f in request.files.getlist("transcripts") if f.filename]
        if not transcripts:
            return jsonify(error="Select at least one transcript file."), 400
        job_id = uuid.uuid4().hex[:10]
        upload_dir = ROOT / "cases" / "_uploads" / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)

        saved_transcripts = [save_upload(f, upload_dir, "t", True) for f in transcripts]
        saved_reqs = [
            save_upload(f, upload_dir, "r", False)
            for f in request.files.getlist("requirements") if f.filename
        ]
        metadata = request.files.get("metadata")
        inputs = {
            "transcripts": saved_transcripts,
            "requirements": saved_reqs,
            "metadata": save_upload(metadata, upload_dir, "m", False) if metadata and metadata.filename else None,
        }
        form = request.form
        options = {
            "engine": form.get("engine", "mock"),
            "ollama_model": form.get("ollama_model", "").strip(),
            "headroom": form.get("headroom", "").strip(),
            "mode": form.get("mode", "guided"),
            "use_rag": form.get("use_rag") == "true",
            "rag_kb": form.get("rag_kb", "finance"),
        }
        if options["engine"] not in {"mock", "ollama", "configured"}:
            return jsonify(error="Unknown reasoning engine."), 400
        job = Job(job_id, options, upload_dir, inputs)
        jobs[job_id] = job
        if options["mode"] == "auto":
            launch(job, "analyse", 1, 12, auto=True)
        else:
            launch(job, "analyse", *GUIDED_PHASES["analyse"][:2])
        return jsonify(id=job_id)

    def save_upload(file, upload_dir: Path, prefix: str, transcript: bool) -> str:
        name = secure_filename(file.filename) or f"{prefix}_file"
        suffix = Path(name).suffix.lower()
        if prefix == "m":
            allowed = {".json"}
        else:
            allowed = TRANSCRIPT_TEXT_EXTS | {".docx"} if transcript else REQUIREMENT_EXTS
        if suffix not in allowed:
            abort(400, f"Unsupported file type: {name}")
        dest = upload_dir / f"{uuid.uuid4().hex[:4]}_{name}" if (upload_dir / name).exists() else upload_dir / name
        file.save(dest)
        if suffix == ".docx" and (transcript or prefix == "r"):
            dest = docx_to_text(dest)
        elif transcript and suffix in TRANSCRIPT_TEXT_EXTS - {".txt", ".md"}:
            renamed = dest.with_suffix(".txt")
            dest.replace(renamed)
            dest = renamed
        return str(dest)

    def docx_to_text(path: Path) -> Path:
        from docx import Document

        document = Document(str(path))
        lines = [p.text for p in document.paragraphs]
        for table in document.tables:
            lines += [" | ".join(cell.text for cell in row.cells) for row in table.rows]
        out = path.with_suffix(".txt")
        out.write_text("\n".join(lines), encoding="utf-8")
        path.unlink()
        return out

    @app.get("/api/jobs/<job_id>")
    def job_status(job_id: str):
        job = get_job(job_id)
        since = int(request.args.get("since", 0))
        with job.lock:
            lines = job.lines[since:]
            total = len(job.lines)
        return jsonify(
            id=job.id, status=job.status, step=job.step, phase=job.phase, case_id=job.case_id,
            error=job.error, options=job.options, lines=lines, next=total,
        )

    @app.post("/api/jobs/<job_id>/cancel")
    def cancel(job_id: str):
        job = get_job(job_id)
        if job.process and job.process.poll() is None:
            job.status = "cancelled"
            job.process.terminate()
            job.log("Run cancelled by user.", "err")
        return jsonify(ok=True)

    @app.post("/api/jobs/<job_id>/retry")
    def retry(job_id: str):
        job = get_job(job_id)
        if job.status not in {"error", "cancelled"}:
            return jsonify(error="Nothing to retry."), 409
        if job.options["mode"] == "auto":
            launch(job, "analyse", 1 if not job.case_id else 2, 12, auto=True)
        elif job.phase == "analyse" and not job.case_id:
            launch(job, "analyse", 1, 3)
        else:
            from_stage, to_stage, _ = GUIDED_PHASES[job.phase]
            launch(job, job.phase, max(from_stage, 2), to_stage)
        return jsonify(ok=True)

    @app.get("/api/jobs/<job_id>/insights")
    def insights(job_id: str):
        job = get_job(job_id)
        if not job.case_id:
            return jsonify({})
        analysis = state_json(job, "03_transcript_analysis.json")
        baseline = state_json(job, "04_requirement_reconciliation.json")
        decomposition = state_json(job, "05_requirement_decomposition.json")
        needs = state_json(job, "06_data_need_specification.json")
        queries = state_json(job, "07_metadata_query_design.json")
        gaps = state_json(job, "10_gap_clarification_analysis.json")
        return jsonify(
            analysis={
                "summary": analysis.get("executive_summary"),
                "signals": analysis.get("confirmed_signals", []),
                "risks": analysis.get("ambiguity_risks", []),
                "assumptions": analysis.get("assumptions_to_validate", []),
                "readiness": analysis.get("readiness"),
            } if analysis else None,
            baseline={
                "summary": baseline.get("summary"),
                "in_scope": baseline.get("in_scope", []),
                "out_of_scope": baseline.get("out_of_scope", []),
            } if baseline else None,
            requirements=[
                {"id": r.get("requirement_id"), "title": r.get("title"), "category": r.get("category")}
                for r in decomposition.get("requirements", [])
            ],
            data_needs=len(needs.get("needs", [])),
            queries=len(queries.get("queries", [])),
            gaps={
                "readiness": gaps.get("overall_readiness"),
                "missing": gaps.get("missing_data", []),
                "conflicts": gaps.get("conflicting_definitions", []),
            } if gaps else None,
        )

    # -- guided step: clarifications

    @app.get("/api/jobs/<job_id>/clarifications")
    def get_clarifications(job_id: str):
        job = get_job(job_id)
        analysis = job.store.load_stage(3, TranscriptAnalysis)
        return jsonify(questions=[
            {"id": q.question_id, "question": q.question, "ambiguity": q.ambiguity,
             "impact": q.business_impact, "options": q.options, "priority": q.priority,
             "answer": q.answer or ""}
            for q in analysis.clarification_questions
        ], readiness=analysis.readiness)

    @app.post("/api/jobs/<job_id>/clarifications")
    def post_clarifications(job_id: str):
        job = get_job(job_id)
        if job.step != "clarify" or job.status != "waiting":
            return jsonify(error="Not waiting for clarifications."), 409
        body = request.get_json(force=True)
        answers = body.get("answers", {})
        store = job.store
        analysis = store.load_stage(3, TranscriptAnalysis)
        for question in analysis.clarification_questions:
            text = (answers.get(question.question_id) or "").strip()
            if text:
                question.answer = text
        if body.get("auto"):
            answer_transcript_questions(store, analysis)
        missing = [q.question_id for q in analysis.clarification_questions if not q.answer]
        if missing:
            return jsonify(error="Answer every question or choose 'Assume the rest': " + ", ".join(missing)), 400
        response = TranscriptClarificationResponse(
            case_id=store.case_id,
            answers=[
                TranscriptClarificationAnswer(question_id=q.question_id, question=q.question, answer=q.answer)
                for q in analysis.clarification_questions
            ],
        )
        store.artifact_path("transcript_clarifications.json").write_text(
            response.model_dump_json(indent=2), encoding="utf-8"
        )
        job.log("Clarification answers saved.", "info")
        launch(job, "build", *GUIDED_PHASES["build"][:2])
        return jsonify(ok=True)

    # -- guided step: validation workbook

    @app.get("/api/jobs/<job_id>/validation")
    def get_validation(job_id: str):
        job = get_job(job_id)
        sheet = load_workbook(workbook_path(job))["Validation Matrix"]
        cols = column_map(sheet)
        rows = []
        for index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if not row[cols["Requirement ID"]]:
                continue
            rows.append({
                "row": index,
                "id": row[cols["Requirement ID"]],
                "title": row[cols["Title"]] or "",
                "description": row[cols["Description"]] or "",
                "paths": row[cols["Metadata Path(s)"]] or "",
                "mapping": row[cols["Metadata Mapping Note"]] or "",
                "query": row[cols["Human Validation Query"]] or "",
                "grounding": row[cols["Grounding Status"]] or "",
                "status": row[cols["Human Status"]] or "",
                "notes": row[cols["Human Notes"]] or "",
                "answer": row[cols["Client Clarification / Answer"]] or "",
            })
        return jsonify(rows=rows, statuses=STATUS_OPTIONS.split(","))

    @app.post("/api/jobs/<job_id>/validation")
    def post_validation(job_id: str):
        job = get_job(job_id)
        if job.step != "validate" or job.status != "waiting":
            return jsonify(error="Not waiting for validation."), 409
        body = request.get_json(force=True)
        path = workbook_path(job)
        if body.get("auto"):
            fill_validation_workbook(job.store)
        else:
            workbook = load_workbook(path)
            sheet = workbook["Validation Matrix"]
            cols = column_map(sheet)
            by_row = {int(item["row"]): item for item in body.get("rows", [])}
            missing = []
            for index, item in by_row.items():
                status = (item.get("status") or "").strip()
                if status not in STATUS_OPTIONS.split(","):
                    missing.append(sheet.cell(index, cols["Requirement ID"] + 1).value)
                    continue
                sheet.cell(index, cols["Human Status"] + 1).value = status
                sheet.cell(index, cols["Human Notes"] + 1).value = item.get("notes") or None
                sheet.cell(index, cols["Client Clarification / Answer"] + 1).value = item.get("answer") or None
            if missing:
                return jsonify(error="Choose a status for: " + ", ".join(map(str, missing))), 400
            workbook.save(path)
        job.log("Validation results saved to the workbook.", "info")
        launch(job, "assess", *GUIDED_PHASES["assess"][:2])
        return jsonify(ok=True)

    @app.post("/api/jobs/<job_id>/workbook")
    def upload_workbook(job_id: str):
        job = get_job(job_id)
        if job.step != "validate" or job.status != "waiting":
            return jsonify(error="Not waiting for validation."), 409
        file = request.files.get("workbook")
        if not file or not file.filename.lower().endswith(".xlsx"):
            return jsonify(error="Upload the completed .xlsx workbook."), 400
        file.save(workbook_path(job))
        job.log("Completed workbook uploaded.", "info")
        launch(job, "assess", *GUIDED_PHASES["assess"][:2])
        return jsonify(ok=True)

    # -- guided step: gap answers

    @app.get("/api/jobs/<job_id>/gaps")
    def get_gaps(job_id: str):
        return jsonify(rows=gap_rows(get_job(job_id)))

    @app.post("/api/jobs/<job_id>/gaps")
    def post_gaps(job_id: str):
        job = get_job(job_id)
        if job.step != "gaps" or job.status != "waiting":
            return jsonify(error="Not waiting for gap answers."), 409
        body = request.get_json(force=True)
        path = workbook_path(job)
        workbook = load_workbook(path)
        sheet = workbook["Gaps & Clarifications"]
        for item in body.get("rows", []):
            text = (item.get("answer") or "").strip()
            if text:
                sheet.cell(int(item["row"]), 3).value = text
        if body.get("auto"):
            for row in sheet.iter_rows(min_row=2):
                if row[1].value and not row[2].value:
                    row[2].value = (
                        "Automated assumption: retain the documented requirement and flag it for "
                        f"customer confirmation during delivery. {AUTOMATED_NOTE}"
                    )
        remaining = [r[0].row for r in sheet.iter_rows(min_row=2) if r[1].value and not r[2].value]
        if remaining:
            return jsonify(error="Answer every gap or choose 'Assume the rest'."), 400
        workbook.save(path)
        job.log("Gap answers saved to the workbook.", "info")
        launch(job, "write", *GUIDED_PHASES["write"][:2])
        return jsonify(ok=True)

    # -- results

    @app.get("/api/jobs/<job_id>/results")
    def results(job_id: str):
        job = get_job(job_id)
        store = job.store
        prd = store.artifact_path("final_prd.md")
        files = sorted(
            p.name for p in store.case_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".md", ".docx", ".pdf", ".xlsx", ".json"}
        )
        feedback = store.artifact_path("feedback.json")
        return jsonify(
            prd=prd.read_text(encoding="utf-8") if prd.exists() else "",
            files=files,
            feedback=json.loads(feedback.read_text(encoding="utf-8")) if feedback.exists() else None,
        )

    @app.get("/api/jobs/<job_id>/files/<path:name>")
    def download(job_id: str, name: str):
        job = get_job(job_id)
        directory = job.store.case_dir.resolve()
        target = (directory / name).resolve()
        if target.parent != directory or not target.is_file():
            abort(404)
        return send_from_directory(directory, name, as_attachment=True)

    @app.post("/api/jobs/<job_id>/feedback")
    def feedback(job_id: str):
        job = get_job(job_id)
        body = request.get_json(force=True)
        job.store.save_feedback({"accepted": bool(body.get("accepted")), "notes": body.get("notes", "")})
        return jsonify(ok=True)

    return app
