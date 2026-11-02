"""Stage 2: Document Parsing.

Extracts raw text from each evidence file and normalizes it into a single
CaseContext object. Only .txt/.md are supported in this local prototype.
"""
from pathlib import Path

from pipeline.case_store import CaseStore
from pipeline.models import CaseContext, TranscriptDoc

SUPPORTED_EXTENSIONS = {".txt", ".md"}


def _read_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        # PDF/DOCX extraction (e.g. pypdf, python-docx) would plug in here.
        raise NotImplementedError(
            f"Unsupported file type '{ext}' for {path.name}. Only .txt/.md are supported."
        )
    return path.read_text(encoding="utf-8")


def run(store: CaseStore) -> CaseContext:
    manifest = store.load_manifest()

    transcripts = [
        TranscriptDoc(filename=name, text=_read_text(store.evidence_dir / name))
        for name in manifest["transcripts"]
    ]

    requirement_doc = None
    if manifest.get("requirement_doc"):
        name = manifest["requirement_doc"]
        requirement_doc = TranscriptDoc(filename=name, text=_read_text(store.evidence_dir / name))

    context = CaseContext(
        case_id=store.case_id,
        transcripts=transcripts,
        requirement_doc=requirement_doc,
    )
    store.save_stage(2, context)
    return context
