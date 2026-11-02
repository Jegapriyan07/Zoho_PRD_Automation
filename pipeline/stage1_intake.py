"""Stage 1: Upload & Case Creation.

Takes paths to one or more transcript files (+ optional requirement doc),
creates a case folder under cases/<case_id>/, and copies the inputs in as
evidence. The transcript count is derived from how many paths are passed in,
not fixed to a specific number.
"""
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from pipeline.case_store import CaseStore


def create_case(
    transcript_paths: list[str],
    requirement_path: Optional[str] = None,
    base_dir: str = "cases",
) -> tuple[str, CaseStore]:
    if not transcript_paths:
        raise ValueError("At least 1 transcript file is required.")

    case_id = f"case_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    store = CaseStore(case_id, base_dir=base_dir)
    store.ensure_dirs()

    for p in transcript_paths:
        store.copy_evidence(p)
    if requirement_path:
        store.copy_evidence(requirement_path)

    store.save_manifest({
        "transcripts": [Path(p).name for p in transcript_paths],
        "requirement_doc": Path(requirement_path).name if requirement_path else None,
    })
    return case_id, store
