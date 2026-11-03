"""Pydantic schemas shared by every pipeline stage.

Each model doubles as the JSON schema handed to Claude (via model_json_schema())
so prompts and parsing stay in sync with a single source of truth.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class TranscriptDoc(BaseModel):
    filename: str
    text: str


class CaseContext(BaseModel):
    case_id: str
    transcripts: list[TranscriptDoc]
    requirement_doc: Optional[TranscriptDoc] = None


class TranscriptClarificationQuestion(BaseModel):
    question_id: str
    question: str
    ambiguity: str
    business_impact: str
    options: list[str] = Field(default_factory=list)
    priority: Literal["blocking", "important", "advisory"]
    related_topics: list[str] = Field(default_factory=list)
    answer: Optional[str] = None


class EvidenceItem(BaseModel):
    source: str
    statement: str
    classification: Literal[
        "client_need", "client_decision", "client_constraint", "vendor_process",
        "commercial_term", "implementation_dependency", "noise"
    ]
    speaker_or_role: Optional[str] = None
    evidence_strength: Literal["explicit", "supported_inference", "unresolved"] = "explicit"


class MetricDefinition(BaseModel):
    name: str
    formula: Optional[str] = None
    grain: Optional[str] = None
    inclusions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    source_precedence: list[str] = Field(default_factory=list)
    validation_method: Optional[str] = None
    status: Literal["confirmed", "assumption", "needs_decision"] = "confirmed"


class ReportRequirement(BaseModel):
    name: str
    purpose: str
    grain: Optional[str] = None
    columns_or_metrics: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    source_requirements: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)


class TranscriptAnalysis(BaseModel):
    executive_summary: str
    confirmed_signals: list[str] = Field(default_factory=list)
    assumptions_to_validate: list[str] = Field(default_factory=list)
    ambiguity_risks: list[str] = Field(default_factory=list)
    clarification_questions: list[TranscriptClarificationQuestion] = Field(default_factory=list)
    readiness: Literal["ready_for_reconciliation", "needs_clarification"]
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    business_objectives: list[str] = Field(default_factory=list)
    source_systems: list[str] = Field(default_factory=list)
    source_of_truth_rules: list[str] = Field(default_factory=list)
    metric_definitions: list[MetricDefinition] = Field(default_factory=list)
    report_requirements: list[ReportRequirement] = Field(default_factory=list)
    commercial_terms: list[str] = Field(default_factory=list)
    delivery_commitments: list[str] = Field(default_factory=list)


class ConflictNote(BaseModel):
    topic: str
    description: str
    sources: list[str] = Field(default_factory=list)


class RequirementBaseline(BaseModel):
    summary: str
    baseline_requirements: list[str]
    conflicts: list[ConflictNote] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    source_of_truth_rules: list[str] = Field(default_factory=list)
    metrics: list[MetricDefinition] = Field(default_factory=list)
    reports: list[ReportRequirement] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    commercial_terms: list[str] = Field(default_factory=list)
    delivery_commitments: list[str] = Field(default_factory=list)


class AtomicRequirement(BaseModel):
    requirement_id: str
    category: Literal["metric", "dimension", "filter", "time_logic", "business_rule"]
    description: str
    source_reference: Optional[str] = None
    evidence: list[str] = Field(default_factory=list)
    source_systems: list[str] = Field(default_factory=list)
    report_surfaces: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    validation_method: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)


class RequirementDecomposition(BaseModel):
    requirements: list[AtomicRequirement]


class RulebookChunk(BaseModel):
    chunk_id: str
    category: str
    title: str
    heading_path: str
    content: str
    score: float
    retrieval_query: str


class RequirementRetrieval(BaseModel):
    requirement_id: str
    queries: list[str]
    chunks: list[RulebookChunk] = Field(default_factory=list)
    grounding_status: Literal["GROUNDED", "NO_MATCH", "ERROR"]
    message: Optional[str] = None


class RulebookRetrievalResult(BaseModel):
    requirements: list[RequirementRetrieval]


class DataConcept(BaseModel):
    concept: str
    concept_type: Literal["entity", "field", "aggregation", "join", "filter_value"]
    notes: Optional[str] = None
    metric_formula: Optional[str] = None
    rulebook_reference: Optional[str] = None
    rulebook_chunk_ids: list[str] = Field(default_factory=list)


class DataNeed(BaseModel):
    requirement_id: str
    data_concepts: list[DataConcept]


class DataNeedSpecification(BaseModel):
    needs: list[DataNeed]


class CandidateQuery(BaseModel):
    requirement_id: str
    purpose: str
    sql: str
    metadata_paths: list[str] = Field(default_factory=list)


class SQLDiscovery(BaseModel):
    queries: list[CandidateQuery]


class MetadataField(BaseModel):
    name: str
    data_type: Optional[str] = None
    description: Optional[str] = None


class MetadataEntity(BaseModel):
    name: str
    module: Optional[str] = None
    description: Optional[str] = None
    fields: list[MetadataField] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)


class WorkspaceMetadata(BaseModel):
    source: str
    entities: list[MetadataEntity]


class HumanValidationRecord(BaseModel):
    requirement_id: str
    validation_status: Literal["Available", "Missing", "Soiled Data", "Partially Available", "Unclear"]
    human_notes: Optional[str] = None
    client_answer: Optional[str] = None


class HumanValidationResult(BaseModel):
    records: list[HumanValidationRecord]


class GapClarificationQuestion(BaseModel):
    topic: str
    question: str
    related_requirement_ids: list[str] = Field(default_factory=list)


class GapAnalysis(BaseModel):
    missing_data: list[str] = Field(default_factory=list)
    conflicting_definitions: list[str] = Field(default_factory=list)
    clarification_questions: list[GapClarificationQuestion] = Field(default_factory=list)
    overall_readiness: Literal["READY", "PARTIALLY READY", "BLOCKED"]


class ScopeDocument(BaseModel):
    markdown: str
