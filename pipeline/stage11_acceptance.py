"""Stage 11: Human Acceptance.

Prints the PRD draft to console (it's already saved as prd_draft.md by
stage 10), prompts the user to accept or leave feedback, and saves the
decision to feedback.json.
"""
from pipeline.case_store import CaseStore


def run(store: CaseStore) -> dict:
    scope_path = store.artifact_path("prd_draft.md")
    print(scope_path.read_text(encoding="utf-8"))
    print("\n" + "=" * 70)

    decision = input("Accept this PRD draft? [y/n]: ").strip().lower()
    notes = ""
    if decision != "y":
        notes = input("Enter feedback notes: ").strip()

    feedback = {"accepted": decision == "y", "notes": notes}
    store.save_feedback(feedback)
    print(f"Feedback saved to {store.artifact_path('feedback.json')}")
    return feedback
