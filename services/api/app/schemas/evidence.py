from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


RelationType = Literal["supports", "contradicts", "qualifies", "not_comparable", "insufficient_evidence", "depends_on"]
ProvenanceBasis = Literal["source_documented", "metadata_derived", "metadata_inferred", "model_inferred", "human_reviewed"]
ReviewStatus = Literal["unreviewed", "accepted", "rejected", "needs_review"]


class PaperRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    doi: str | None
    title: str
    authors: list
    abstract: str | None
    publication_year: int | None
    publisher: str | None
    source_provider: str
    external_id: str | None
    landing_url: str | None


class PaperSearchResult(BaseModel):
    provider: str
    external_id: str | None = None
    doi: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    publication_year: int | None = None
    publisher: str | None = None
    landing_url: str | None = None


class PaperImport(BaseModel):
    provider: str = Field(default="manual", max_length=40)
    external_id: str | None = Field(default=None, max_length=500)
    doi: str | None = Field(default=None, max_length=500)
    title: str = Field(min_length=2, max_length=4000)
    authors: list[str] = Field(default_factory=list, max_length=300)
    abstract: str | None = None
    publication_year: int | None = Field(default=None, ge=1600, le=2200)
    publisher: str | None = None
    landing_url: str | None = None


class StudyCreate(BaseModel):
    study_type: str | None = None
    population: str | None = None
    method: str | None = None
    intervention: str | None = None
    outcomes: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    extraction_basis: Literal["source_documented", "model_inferred", "human_reviewed", "unreviewed"] = "unreviewed"


class PassageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    paper_version_id: str
    section_title: str | None
    page_number: int | None
    text: str
    text_hash: str
    extraction_method: str


class ClaimCreate(BaseModel):
    run_id: str
    statement: str = Field(min_length=8, max_length=6000)
    scope: dict = Field(default_factory=dict)
    uncertainty_notes: str | None = None


class ClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    run_id: str
    statement: str
    scope: dict
    assessment: str
    review_required: bool
    uncertainty_notes: str | None
    created_at: datetime


class EvidenceRelationCreate(BaseModel):
    passage_id: str | None = None
    related_claim_id: str | None = None
    relation_type: RelationType
    provenance_basis: ProvenanceBasis = "model_inferred"
    confidence: float | None = Field(default=None, ge=0, le=1)
    reviewer_status: ReviewStatus = "unreviewed"
    rationale: str | None = None

    @model_validator(mode="after")
    def exactly_one_target(self):
        if (self.passage_id is None) == (self.related_claim_id is None):
            raise ValueError("Provide exactly one of passage_id or related_claim_id.")
        if self.related_claim_id and self.relation_type not in {"depends_on", "supports", "contradicts", "qualifies", "not_comparable"}:
            raise ValueError("Invalid claim-to-claim relationship type.")
        return self


class EvidenceRelationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    claim_id: str
    passage_id: str | None
    related_claim_id: str | None
    relation_type: str
    provenance_basis: str
    confidence: float | None
    reviewer_status: str
    rationale: str | None


class PaperDependencyCreate(BaseModel):
    dependent_paper_id: str
    depends_on_paper_id: str
    relation_type: Literal["derived_from", "same_dataset", "duplicate_or_overlap", "cites_as_primary_source"] = "derived_from"
    provenance_basis: ProvenanceBasis = "metadata_inferred"
    rationale: str = Field(min_length=4, max_length=3000)
    confidence: float | None = Field(default=None, ge=0, le=1)


class SourceEventCreate(BaseModel):
    event_type: Literal["correction", "retraction", "expression_of_concern", "new_version", "metadata_change", "conflicting_study"]
    event_date: datetime | None = None
    source_url: str | None = None
    description: str = Field(min_length=8, max_length=6000)
    verification_status: Literal["unverified", "metadata_confirmed", "human_verified"] = "unverified"
    metadata_snapshot: dict = Field(default_factory=dict)


class SourceEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    paper_id: str
    event_type: str
    event_date: datetime | None
    observed_at: datetime
    source_url: str | None
    description: str
    verification_status: str
