from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Employee, EmployeeAffiliation, IdentityReview, ReviewStatus
from ..pagination import clamp_limit, decode_cursor, encode_cursor
from ..schemas import (
    AffiliationCreateRequest,
    AffiliationOut,
    AffiliationUpdateRequest,
    EmployeeCreateRequest,
    EmployeeCreateResponse,
    EmployeeDetailResponse,
    EmployeeListItem,
    EmployeeListResponse,
    EmployeeSearchRequest,
    EmployeeUpdateRequest,
    ReviewPendingResponse,
)
from ..security import CurrentUser, get_current_user, require_company_access
from ..services import audit
from ..services.employees import register_employee
from ..services.idempotency import check_or_conflict, hash_request, store
from ..services.normalization import normalize_english_name
from ..services.validation import FieldError, validate_employee_input

router = APIRouter(prefix="/api/v1/employees", tags=["employees"])


def _affiliation_out(aff: EmployeeAffiliation) -> AffiliationOut:
    return AffiliationOut(
        id=aff.id,
        company_code=aff.company.code,
        company_name=aff.company.name,
        organization_code=aff.organization.code if aff.organization else None,
        organization_name=aff.organization.name if aff.organization else None,
        existing_employee_number=aff.existing_employee_number,
        job_title=aff.job_title,
        remarks=aff.remarks,
    )


def _employee_detail(employee: Employee, user: CurrentUser) -> EmployeeDetailResponse:
    show_sensitive = user.can_view_sensitive_fields()
    return EmployeeDetailResponse(
        unified_employee_number=employee.unified_employee_number,
        english_name=employee.english_name_original,
        date_of_birth=employee.date_of_birth.isoformat() if show_sensitive else None,
        status=employee.status,
        version=employee.version,
        affiliations=[_affiliation_out(a) for a in employee.affiliations],
        created_at=employee.created_at,
        updated_at=employee.updated_at,
    )


@router.post("", response_model=EmployeeCreateResponse | ReviewPendingResponse, status_code=201)
def create_employee(
    payload: EmployeeCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    require_company_access(user, payload.company_code)
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail={"code": "MISSING_IDEMPOTENCY_KEY", "message": "Idempotency-Key header is required", "field_errors": []},
        )

    raw = payload.model_dump()
    req_hash = hash_request(raw)
    existing = check_or_conflict(db, user.sub, idempotency_key, "POST /employees", req_hash)
    if existing is not None:
        return _response_from_status(existing.status_code, existing.response_body)

    result = register_employee(db, raw, actor=user.sub)

    if result.status == "CREATED":
        body = {"status": "CREATED", "unified_employee_number": result.employee.unified_employee_number, "version": result.employee.version}
        status_code = 201
    elif result.status == "EXISTING":
        body = {"status": "EXISTING", "unified_employee_number": result.employee.unified_employee_number, "version": result.employee.version}
        status_code = 200
    else:
        body = {"status": "REVIEW_REQUIRED", "review_id": result.review.id}
        status_code = 202

    store(db, user.sub, idempotency_key, "POST /employees", req_hash, status_code, body)
    db.commit()
    return _response_from_status(status_code, body)


def _response_from_status(status_code: int, body: dict):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content=body)


@router.get("", response_model=EmployeeListResponse)
def list_employees(
    company_code: str | None = None,
    status_filter: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    offset = decode_cursor(cursor)
    limit = clamp_limit(limit)

    stmt = select(Employee).join(EmployeeAffiliation).distinct()
    if company_code:
        require_company_access(user, company_code)
        stmt = stmt.where(EmployeeAffiliation.company.has(code=company_code))
    elif "*" not in user.companies and not user.has_role("CENTRAL_ADMIN"):
        from ..models import Company

        stmt = stmt.where(EmployeeAffiliation.company_id.in_(
            select(Company.id).where(Company.code.in_(user.companies))
        ))
    if status_filter:
        stmt = stmt.where(Employee.status == status_filter)

    stmt = stmt.order_by(Employee.created_at.desc()).offset(offset).limit(limit + 1)
    rows = db.execute(stmt).scalars().all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        EmployeeListItem(
            unified_employee_number=e.unified_employee_number,
            english_name=e.english_name_original,
            status=e.status,
            company_codes=[a.company.code for a in e.affiliations],
        )
        for e in rows
    ]
    next_cursor = encode_cursor(offset + limit) if has_more else None
    return EmployeeListResponse(items=items, next_cursor=next_cursor)


@router.post("/search", response_model=EmployeeListResponse)
def search_employees(
    payload: EmployeeSearchRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    offset = decode_cursor(payload.cursor)
    limit = clamp_limit(payload.limit)

    stmt = select(Employee).join(EmployeeAffiliation).distinct()

    if payload.unified_employee_number:
        stmt = stmt.where(Employee.unified_employee_number == payload.unified_employee_number)
    if payload.english_name:
        needle = normalize_english_name(payload.english_name)
        stmt = stmt.where(Employee.english_name_normalized.ilike(f"%{needle}%"))
    if payload.status:
        stmt = stmt.where(Employee.status == payload.status)
    if payload.date_of_birth:
        if not user.can_view_sensitive_fields():
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN_FIELD", "message": "No permission to search by date_of_birth", "field_errors": []})
        stmt = stmt.where(Employee.date_of_birth == payload.date_of_birth)
    if payload.existing_employee_number:
        stmt = stmt.where(EmployeeAffiliation.existing_employee_number == payload.existing_employee_number)
    if payload.job_title:
        stmt = stmt.where(EmployeeAffiliation.job_title.ilike(f"%{payload.job_title}%"))
    if payload.company_code:
        require_company_access(user, payload.company_code)
        stmt = stmt.where(EmployeeAffiliation.company.has(code=payload.company_code))
    else:
        if not user.has_role("CENTRAL_ADMIN") and "*" not in user.companies:
            from ..models import Company

            stmt = stmt.where(EmployeeAffiliation.company_id.in_(
                select(Company.id).where(Company.code.in_(user.companies))
            ))
    if payload.organization_code:
        stmt = stmt.where(EmployeeAffiliation.organization.has(code=payload.organization_code))

    stmt = stmt.order_by(Employee.created_at.desc()).offset(offset).limit(limit + 1)
    rows = db.execute(stmt).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        EmployeeListItem(
            unified_employee_number=e.unified_employee_number,
            english_name=e.english_name_original,
            status=e.status,
            company_codes=[a.company.code for a in e.affiliations],
        )
        for e in rows
    ]
    next_cursor = encode_cursor(offset + limit) if has_more else None
    audit.record(db, actor=user.sub, action="EMPLOYEE_SEARCH", target_type="employee", details={})
    db.commit()
    return EmployeeListResponse(items=items, next_cursor=next_cursor)


@router.get("/{unified_employee_number}", response_model=EmployeeDetailResponse)
def get_employee(
    unified_employee_number: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    employee = db.execute(
        select(Employee).where(Employee.unified_employee_number == unified_employee_number)
    ).scalar_one_or_none()
    if employee is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Employee not found", "field_errors": []})

    accessible_codes = {a.company.code for a in employee.affiliations}
    if not user.has_role("CENTRAL_ADMIN") and "*" not in user.companies:
        if not accessible_codes.intersection(user.companies):
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Employee not found", "field_errors": []})

    audit.record(db, actor=user.sub, action="EMPLOYEE_VIEWED", target_type="employee", target_id=employee.id)
    db.commit()
    return _employee_detail(employee, user)


@router.patch("/{unified_employee_number}", response_model=EmployeeDetailResponse | ReviewPendingResponse)
def update_employee(
    unified_employee_number: str,
    payload: EmployeeUpdateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    employee = db.execute(
        select(Employee).where(Employee.unified_employee_number == unified_employee_number)
    ).scalar_one_or_none()
    if employee is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Employee not found", "field_errors": []})

    accessible_codes = {a.company.code for a in employee.affiliations}
    if not any(user.can_access_company(c) for c in accessible_codes):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "No access", "field_errors": []})

    if payload.version != employee.version:
        raise HTTPException(
            status_code=409,
            detail={"code": "VERSION_CONFLICT", "message": "The record was modified by someone else", "field_errors": []},
        )

    if payload.status:
        employee.status = payload.status

    changes = {"status": payload.status} if payload.status else {}
    employee.version += 1
    employee.updated_by = user.sub
    employee.updated_at = datetime.utcnow()
    audit.record(db, actor=user.sub, action="EMPLOYEE_UPDATED", target_type="employee", target_id=employee.id, details=changes)
    db.commit()
    db.refresh(employee)
    return _employee_detail(employee, user)


@router.post("/{unified_employee_number}/affiliations", response_model=AffiliationOut, status_code=201)
def add_affiliation(
    unified_employee_number: str,
    payload: AffiliationCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_company_access(user, payload.company_code)
    employee = db.execute(
        select(Employee).where(Employee.unified_employee_number == unified_employee_number)
    ).scalar_one_or_none()
    if employee is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Employee not found", "field_errors": []})

    validated = validate_employee_input(
        db,
        {
            "english_name": employee.english_name_original,
            "date_of_birth": employee.date_of_birth,
            "existing_employee_number": payload.existing_employee_number,
            "remarks": payload.remarks,
            "company_code": payload.company_code,
            "organization_code": payload.organization_code,
            "job_title": payload.job_title,
        },
    )

    if payload.existing_employee_number:
        conflict = db.execute(
            select(EmployeeAffiliation).where(
                EmployeeAffiliation.company_id == validated.company.id,
                EmployeeAffiliation.existing_employee_number == payload.existing_employee_number,
            )
        ).scalar_one_or_none()
        if conflict is not None:
            raise FieldError([{"field": "existing_employee_number", "code": "ALREADY_MAPPED", "message": "already mapped to another employee in this company"}])

    affiliation = EmployeeAffiliation(
        employee_id=employee.id,
        company_id=validated.company.id,
        organization_id=validated.organization.id if validated.organization else None,
        existing_employee_number=validated.existing_employee_number,
        job_title=validated.job_title,
        remarks=validated.remarks,
    )
    db.add(affiliation)
    audit.record(db, actor=user.sub, action="AFFILIATION_ADDED", target_type="employee", target_id=employee.id, details={"company_id": validated.company.id})
    db.commit()
    db.refresh(affiliation)
    return _affiliation_out(affiliation)


@router.patch("/{unified_employee_number}/affiliations/{affiliation_id}", response_model=AffiliationOut)
def update_affiliation(
    unified_employee_number: str,
    affiliation_id: str,
    payload: AffiliationUpdateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    affiliation = db.get(EmployeeAffiliation, affiliation_id)
    if affiliation is None or affiliation.employee.unified_employee_number != unified_employee_number:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Affiliation not found", "field_errors": []})

    require_company_access(user, affiliation.company.code)

    if payload.organization_code is not None:
        from ..models import Organization

        org = db.execute(
            select(Organization).where(
                Organization.code == payload.organization_code,
                Organization.company_id == affiliation.company_id,
            )
        ).scalar_one_or_none()
        if org is None:
            raise FieldError([{"field": "organization_code", "code": "UNKNOWN_ORGANIZATION", "message": "invalid organization for this company"}])
        affiliation.organization_id = org.id

    if payload.job_title is not None:
        affiliation.job_title = payload.job_title
    if payload.remarks is not None:
        affiliation.remarks = payload.remarks

    affiliation.updated_at = datetime.utcnow()
    audit.record(db, actor=user.sub, action="AFFILIATION_UPDATED", target_type="employee", target_id=affiliation.employee_id)
    db.commit()
    db.refresh(affiliation)
    return _affiliation_out(affiliation)
