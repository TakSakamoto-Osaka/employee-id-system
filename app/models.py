import enum
import uuid
from datetime import datetime, date

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
    BigInteger,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class EmployeeStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ReviewStatus(str, enum.Enum):
    PENDING = "PENDING"
    LINKED = "LINKED"
    NEW_NUMBER = "NEW_NUMBER"
    REJECTED = "REJECTED"


class ImportJobStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RowStatus(str, enum.Enum):
    PENDING = "PENDING"
    CREATED = "CREATED"
    EXISTING = "EXISTING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


class BatchStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    organizations: Mapped[list["Organization"]] = relationship(back_populates="company")


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_org_company_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    company: Mapped["Company"] = relationship(back_populates="organizations")


class Employee(Base):
    """Spec 4.1: unified employee number E + 7 digit sequence + Luhn check digit."""

    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    unified_employee_number: Mapped[str] = mapped_column(
        String(9), unique=True, nullable=False, index=True
    )
    english_name_original: Mapped[str] = mapped_column(String(200), nullable=False)
    english_name_normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    normalization_version: Mapped[int] = mapped_column(Integer, nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=EmployeeStatus.ACTIVE.value, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    affiliations: Mapped[list["EmployeeAffiliation"]] = relationship(back_populates="employee")


Index("ix_employees_name_dob", Employee.english_name_normalized, Employee.date_of_birth)


class EmployeeAffiliation(Base):
    __tablename__ = "employee_affiliations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    existing_employee_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    employee: Mapped["Employee"] = relationship(back_populates="affiliations")
    company: Mapped["Company"] = relationship()
    organization: Mapped["Organization | None"] = relationship()


# Spec 8.1: 会社と既存社員番号は初期仕様では同一社員への対応のみを許可する。
Index(
    "uq_affiliation_company_existing_number",
    EmployeeAffiliation.company_id,
    EmployeeAffiliation.existing_employee_number,
    unique=True,
    postgresql_where=EmployeeAffiliation.existing_employee_number.isnot(None),
    sqlite_where=EmployeeAffiliation.existing_employee_number.isnot(None),
)


class IdentityReview(Base):
    """Spec 4.2/4.3: 確認待ちデータ。通常の社員マスタと分離して保存する。"""

    __tablename__ = "identity_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    input_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    candidate_employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id"), nullable=True
    )
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=ReviewStatus.PENDING.value, nullable=False
    )
    resolution_employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id"), nullable=True
    )
    resolved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    candidate_employee: Mapped["Employee | None"] = relationship(foreign_keys=[candidate_employee_id])
    resolution_employee: Mapped["Employee | None"] = relationship(foreign_keys=[resolution_employee_id])


class EmployeeNumberAlias(Base):
    """Spec 4.3: 統合元番号を廃止状態で保持し、統合先社員へ誘導する。"""

    __tablename__ = "employee_number_aliases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    alias_number: Mapped[str] = mapped_column(String(9), unique=True, nullable=False)
    target_employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    performed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    file_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    executed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    company_scope: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=ImportJobStatus.UPLOADED.value, nullable=False
    )
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    existing_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancelled_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Pre-validation preview counts (spec 6.2 step 2) - informational only,
    # actual execution can differ (spec 6.2 step 4).
    preview_new_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    preview_existing_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    preview_review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ImportRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (UniqueConstraint("job_id", "row_number", name="uq_import_job_row"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("import_jobs.id"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    input_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=RowStatus.PENDING.value, nullable=False)
    employee_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    unified_employee_number: Mapped[str | None] = mapped_column(String(9), nullable=True)
    review_id: Mapped[str | None] = mapped_column(ForeignKey("identity_reviews.id"), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("caller_id", "idempotency_key", name="uq_idem_caller_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    caller_id: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(100), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EmployeeBatch(Base):
    __tablename__ = "employee_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    caller_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=BatchStatus.QUEUED.value, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    existing_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_required_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancelled_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def processed_count(self) -> int:
        return self.created_count + self.existing_count + self.review_required_count + self.error_count

    @property
    def pending_count(self) -> int:
        return max(self.total_count - self.processed_count - self.cancelled_count, 0)


class EmployeeBatchRecord(Base):
    __tablename__ = "employee_batch_records"
    __table_args__ = (
        UniqueConstraint("batch_id", "record_index", name="uq_batch_record_index"),
        UniqueConstraint("batch_id", "client_record_id", name="uq_batch_client_record_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("employee_batches.id"), nullable=False)
    record_index: Mapped[int] = mapped_column(Integer, nullable=False)
    client_record_id: Mapped[str] = mapped_column(String(100), nullable=False)
    input_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=RowStatus.PENDING.value, nullable=False)
    employee_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    unified_employee_number: Mapped[str | None] = mapped_column(String(9), nullable=True)
    review_id: Mapped[str | None] = mapped_column(ForeignKey("identity_reviews.id"), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class MatchLock(Base):
    """Serializes matching->confirmation per matching key (spec 4.2).

    A row is inserted (or reused) per normalized-name+DOB key, and locked
    with SELECT ... FOR UPDATE for the duration of the matching transaction
    on PostgreSQL. This avoids two concurrent requests both deciding
    "no candidate" for the same key and creating duplicate employees.
    """

    __tablename__ = "match_locks"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)


class Counter(Base):
    """Atomic counters, used instead of MAX+1 for number generation (spec 4.1)."""

    __tablename__ = "counters"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
