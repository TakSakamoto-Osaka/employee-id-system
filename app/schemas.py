from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ---- Employees -------------------------------------------------------

class EmployeeCreateRequest(BaseModel):
    english_name: str = Field(max_length=200)
    date_of_birth: str
    existing_employee_number: str | None = Field(default=None, max_length=100)
    remarks: str | None = Field(default=None, max_length=2000)
    company_code: str
    organization_code: str | None = None
    job_title: str | None = Field(default=None, max_length=200)


class EmployeeCreateResponse(BaseModel):
    status: Literal["CREATED", "EXISTING"]
    unified_employee_number: str
    version: int


class ReviewPendingResponse(BaseModel):
    status: Literal["REVIEW_REQUIRED"] = "REVIEW_REQUIRED"
    review_id: str


class AffiliationOut(BaseModel):
    id: str
    company_code: str
    company_name: str
    organization_code: str | None
    organization_name: str | None
    existing_employee_number: str | None
    job_title: str | None
    remarks: str | None = None

    model_config = {"from_attributes": True}


class EmployeeDetailResponse(BaseModel):
    unified_employee_number: str
    english_name: str
    date_of_birth: str | None = None
    status: str
    version: int
    affiliations: list[AffiliationOut]
    created_at: datetime
    updated_at: datetime


class EmployeeListItem(BaseModel):
    unified_employee_number: str
    english_name: str
    status: str
    company_codes: list[str]


class EmployeeListResponse(BaseModel):
    items: list[EmployeeListItem]
    next_cursor: str | None = None


class EmployeeSearchRequest(BaseModel):
    unified_employee_number: str | None = None
    english_name: str | None = None
    existing_employee_number: str | None = None
    company_code: str | None = None
    organization_code: str | None = None
    job_title: str | None = None
    status: str | None = None
    date_of_birth: str | None = None
    cursor: str | None = None
    limit: int = 50

    @field_validator("limit")
    @classmethod
    def clamp_limit(cls, v: int) -> int:
        return max(1, min(v, 200))


class EmployeeUpdateRequest(BaseModel):
    version: int
    status: str | None = None
    remarks: str | None = None
    job_title: str | None = None


# ---- Affiliations ------------------------------------------------------

class AffiliationCreateRequest(BaseModel):
    company_code: str
    organization_code: str | None = None
    existing_employee_number: str | None = Field(default=None, max_length=100)
    job_title: str | None = Field(default=None, max_length=200)
    remarks: str | None = Field(default=None, max_length=2000)


class AffiliationUpdateRequest(BaseModel):
    version: int
    organization_code: str | None = None
    job_title: str | None = None
    remarks: str | None = None


# ---- Identity reviews ---------------------------------------------------

class IdentityReviewSummary(BaseModel):
    review_id: str
    reason: str
    status: str
    company_code: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class IdentityReviewListResponse(BaseModel):
    items: list[IdentityReviewSummary]
    next_cursor: str | None = None


class IdentityReviewResolveRequest(BaseModel):
    action: Literal["LINK", "NEW_NUMBER", "REJECT"]
    target_unified_employee_number: str | None = None


class IdentityReviewResolveResponse(BaseModel):
    status: str
    unified_employee_number: str | None = None


# ---- Companies / Organizations ------------------------------------------

class CompanyOut(BaseModel):
    code: str
    name: str
    active: bool

    model_config = {"from_attributes": True}


class CompanyCreateRequest(BaseModel):
    code: str = Field(max_length=50)
    name: str = Field(max_length=200)


class OrganizationOut(BaseModel):
    code: str
    name: str
    company_code: str
    parent_organization_code: str | None = None
    active: bool


class OrganizationCreateRequest(BaseModel):
    code: str = Field(max_length=50)
    name: str = Field(max_length=200)
    company_code: str
    parent_organization_code: str | None = None


# ---- JSON bulk batches (spec 7.4) ---------------------------------------

class EmployeeBatchItem(BaseModel):
    client_record_id: str = Field(min_length=1, max_length=100)
    english_name: str | None = None
    date_of_birth: str | None = None
    existing_employee_number: str | None = None
    remarks: str | None = None
    company_code: str | None = None
    organization_code: str | None = None
    job_title: str | None = None


class EmployeeBatchCreateRequest(BaseModel):
    employees: list[EmployeeBatchItem] = Field(min_length=1)


class EmployeeBatchAcceptedResponse(BaseModel):
    batch_id: str
    status: str
    total_count: int
    status_url: str
    results_url: str


class EmployeeBatchStatusResponse(BaseModel):
    batch_id: str
    status: str
    total_count: int
    processed_count: int
    created_count: int
    existing_count: int
    review_required_count: int
    error_count: int
    cancelled_count: int
    pending_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class BatchResultError(BaseModel):
    code: str
    message: str
    field_errors: list[dict] = []


class EmployeeBatchResultItem(BaseModel):
    record_index: int
    client_record_id: str
    status: str
    unified_employee_number: str | None = None
    review_id: str | None = None
    error: BatchResultError | None = None


class EmployeeBatchResultsResponse(BaseModel):
    batch_id: str
    items: list[EmployeeBatchResultItem]
    next_cursor: str | None = None


# ---- CSV import jobs (spec 6, 7.2) --------------------------------------

class ImportJobCreatedResponse(BaseModel):
    job_id: str
    status: str


class ImportJobStatusResponse(BaseModel):
    job_id: str
    status: str
    total_count: int
    created_count: int
    existing_count: int
    review_count: int
    error_count: int
    cancelled_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ImportRowResult(BaseModel):
    row_number: int
    status: str
    unified_employee_number: str | None = None
    review_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class ImportJobResultsResponse(BaseModel):
    job_id: str
    items: list[ImportRowResult]
    next_cursor: str | None = None


# ---- Auth (dev only) -----------------------------------------------------

class DevTokenRequest(BaseModel):
    sub: str
    display_name: str
    roles: list[str]
    companies: list[str]


class DevTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
