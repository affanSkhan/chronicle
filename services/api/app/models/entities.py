from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResearchProject(Base):
    __tablename__ = "research_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    research_question: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    runs: Mapped[list["ResearchRun"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(24), default="deep", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False, index=True)
    max_sources: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    project: Mapped[ResearchProject | None] = relationship(back_populates="runs")
    claims: Mapped[list["Claim"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    report_versions: Mapped[list["ReportVersion"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (UniqueConstraint("doi", name="uq_papers_doi"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    doi: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_provider: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    landing_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    versions: Mapped[list["PaperVersion"]] = relationship(back_populates="paper", cascade="all, delete-orphan")
    source_events: Mapped[list["SourceEvent"]] = relationship(back_populates="paper", cascade="all, delete-orphan")


class PaperVersion(Base):
    __tablename__ = "paper_versions"
    __table_args__ = (UniqueConstraint("paper_id", "version_label", name="uq_paper_version_label"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    version_label: Mapped[str] = mapped_column(String(120), default="initial", nullable=False)
    publication_status: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False, index=True)
    publication_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    status_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    paper: Mapped[Paper] = relationship(back_populates="versions")
    passages: Mapped[list["Passage"]] = relationship(back_populates="paper_version", cascade="all, delete-orphan")


class Study(Base):
    __tablename__ = "studies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    study_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    population: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    intervention: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcomes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    limitations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    extraction_basis: Mapped[str] = mapped_column(String(40), default="unreviewed", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Passage(Base):
    __tablename__ = "passages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_version_id: Mapped[str] = mapped_column(ForeignKey("paper_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    extraction_method: Mapped[str] = mapped_column(String(40), default="pymupdf", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    paper_version: Mapped[PaperVersion] = relationship(back_populates="passages")
    evidence_relations: Mapped[list["EvidenceRelation"]] = relationship(back_populates="passage")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    assessment: Mapped[str] = mapped_column(String(40), default="unassessed", nullable=False, index=True)
    review_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uncertainty_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    run: Mapped[ResearchRun] = relationship(back_populates="claims")
    evidence_relations: Mapped[list["EvidenceRelation"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", foreign_keys="EvidenceRelation.claim_id"
    )


class EvidenceRelation(Base):
    __tablename__ = "evidence_relations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    passage_id: Mapped[str | None] = mapped_column(ForeignKey("passages.id", ondelete="CASCADE"), nullable=True, index=True)
    related_claim_id: Mapped[str | None] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=True, index=True)
    relation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    provenance_basis: Mapped[str] = mapped_column(String(40), default="model_inferred", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewer_status: Mapped[str] = mapped_column(String(40), default="unreviewed", nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    claim: Mapped[Claim] = relationship(back_populates="evidence_relations", foreign_keys=[claim_id])
    passage: Mapped[Passage | None] = relationship(back_populates="evidence_relations")
    related_claim: Mapped[Claim | None] = relationship(foreign_keys=[related_claim_id])


class PaperDependency(Base):
    __tablename__ = "paper_dependencies"
    __table_args__ = (UniqueConstraint("dependent_paper_id", "depends_on_paper_id", "relation_type", name="uq_paper_dependency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dependent_paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    depends_on_paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(40), default="derived_from", nullable=False)
    provenance_basis: Mapped[str] = mapped_column(String(40), default="metadata_inferred", nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SourceEvent(Base):
    __tablename__ = "source_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(40), default="unverified", nullable=False)
    metadata_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ReportVersion(Base):
    __tablename__ = "report_versions"
    __table_args__ = (UniqueConstraint("run_id", "version_number", name="uq_report_run_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(ForeignKey("report_versions.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    run: Mapped[ResearchRun] = relationship(back_populates="report_versions")
