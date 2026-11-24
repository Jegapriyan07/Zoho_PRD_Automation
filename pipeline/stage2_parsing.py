"""Stage 2: Document Parsing.

Extracts raw text from each evidence file and normalizes it into a single
CaseContext object. .txt/.md are read directly; images (.png/.jpg/.jpeg/.webp/.gif)
are transcribed with the LLM's vision input and cached next to the evidence.
"""
from pathlib import Path
from typing import Callable

from pipeline.case_store import CaseStore
from pipeline.claude_client import IMAGE_MEDIA_TYPES
from pipeline.models import CaseContext, TranscriptDoc

TEXT_EXTENSIONS = {".txt", ".md"}
IMAGE_EXTENSIONS = set(IMAGE_MEDIA_TYPES)
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS

IMAGE_SYSTEM_PROMPT = (
    "You transcribe customer requirement images (screenshots, slides, scanned pages, whiteboards) "
    "into plain text for a requirements analyst."
)
IMAGE_USER_PROMPT = (
    "Transcribe every requirement visible in this image faithfully and completely. Preserve requirement "
    "numbers, headings, table rows, field/metric names, formulas, filters, and any section or page reference. "
    "For charts, mock-ups or diagrams, describe the report layout, metrics, dimensions, and filters shown. "
    "Mark unreadable text as [illegible]. Do not summarize, interpret, or add anything that is not visible. "
    "Output plain text or Markdown only."
)


def _read_text(path: Path, claude_factory: Callable | None) -> str:
    ext = path.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return path.read_text(encoding="utf-8")
    if ext in IMAGE_EXTENSIONS:
        cache = path.with_name(f"{path.name}.extracted.md")
        if cache.exists():
            return cache.read_text(encoding="utf-8")
        if claude_factory is None:
            raise RuntimeError(f"An LLM client is required to read image evidence {path.name}.")
        text = claude_factory().extract_image_text(IMAGE_SYSTEM_PROMPT, IMAGE_USER_PROMPT, path).strip()
        if not text:
            raise RuntimeError(f"No text could be extracted from image {path.name}.")
        cache.write_text(text, encoding="utf-8")
        return text
    # PDF/DOCX extraction (e.g. pypdf, python-docx) would plug in here.
    raise NotImplementedError(
        f"Unsupported file type '{ext}' for {path.name}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
    )


def run(store: CaseStore, claude_factory: Callable | None = None) -> CaseContext:
    manifest = store.load_manifest()

    def load(name: str) -> TranscriptDoc:
        return TranscriptDoc(filename=name, text=_read_text(store.evidence_dir / name, claude_factory))

    requirement_names = list(manifest.get("requirement_docs") or [])
    if not requirement_names and manifest.get("requirement_doc"):
        requirement_names = [manifest["requirement_doc"]]

    context = CaseContext(
        case_id=store.case_id,
        transcripts=[load(name) for name in manifest["transcripts"]],
        requirement_docs=[load(name) for name in requirement_names],
    )
    store.save_stage(2, context)
    return context
