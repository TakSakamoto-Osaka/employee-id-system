from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Employee, IdentityReview, ReviewStatus
from ..pagination import clamp_limit, decode_cursor, encode_cursor
from ..schemas import (
    IdentityReviewListResponse,
    IdentityReviewResolveRequest,
    IdentityReviewResolveResponse,
    IdentityReviewSummary,
)
from ..security import CurrentUser, get_current_user, require_company_access
from ..services.employees import (
    resolve_review_link,
    resolve_review_new_number,
    resolve_review_reject,
)

router = APIRouter(prefix="/api/v1/identity-reviews", tags=["identity-reviews"])


def _company_code(db: Session, company_id: str | None) -> str | None:
    if not company_id:
        return None
    from ..models import Company

    company = db.get(Company, company_id)
    return company.code if company else None


@router.get("", response_model=IdentityReviewListResponse)
def list_reviews(
    status_filter: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    offset = decode_cursor(cursor)
    limit = clamp_limit(limit)

    stmt = select(IdentityReview)
    if status_filter:
        stmt = stmt.where(IdentityReview.status == status_filter)
    else:
        stmt = stmt.where(IdentityReview.status == ReviewStatus.PENDING.value)

    if not user.has_role("CENTRAL_ADMIN") and "*" not in user.companies:
        from ..models import Company

        stmt = stmt.where(
            IdentityReview.company_id.is_(None)
            | IdentityReview.company_id.in_(select(Company.id).where(Company.code.in_(user.companies)))
        )

    stmt = stmt.order_by(IdentityReview.created_at.asc()).offset(offset).limit(limit + 1)
    rows = db.execute(stmt).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        IdentityReviewSummary(
            review_id=r.id,
            reason=r.reason,
            status=r.status,
            company_code=_company_code(db, r.company_id),
            created_at=r.created_at,
        )
        for r in rows
    ]
    next_cursor = encode_cursor(offset + limit) if has_more else None
    return IdentityReviewListResponse(items=items, next_cursor=next_cursor)


@router.get("/{review_id}")
def get_review(review_id: str, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    review = db.get(IdentityReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "review not found", "field_errors": []})
    if review.company_id and not user.has_role("CENTRAL_ADMIN") and "*" not in user.companies:
        require_company_access(user, _company_code(db, review.company_id))

    resolution_number = None
    if review.resolution_employee_id:
        emp = db.get(Employee, review.resolution_employee_id)
        resolution_number = emp.unified_employee_number if emp else None

    return {
        "review_id": review.id,
        "status": review.status,
        "reason": review.reason,
        "resolved_by": review.resolved_by,
        "resolved_at": review.resolved_at,
        "unified_employee_number": resolution_number,
    }


@router.post("/{review_id}/resolve", response_model=IdentityReviewResolveResponse)
def resolve_review(
    review_id: str,
    payload: IdentityReviewResolveRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    review = db.get(IdentityReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "review not found", "field_errors": []})
    if review.status != ReviewStatus.PENDING.value:
        raise HTTPException(status_code=409, detail={"code": "ALREADY_RESOLVED", "message": "review already resolved", "field_errors": []})

    require_company_access(user, _company_code(db, review.company_id))

    if payload.action == "LINK":
        if not payload.target_unified_employee_number:
            raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "target_unified_employee_number is required for LINK", "field_errors": []})
        target = db.execute(
            select(Employee).where(Employee.unified_employee_number == payload.target_unified_employee_number)
        ).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "target employee not found", "field_errors": []})
        employee = resolve_review_link(db, review, target, user.sub)
        db.commit()
        return IdentityReviewResolveResponse(status="LINKED", unified_employee_number=employee.unified_employee_number)

    if payload.action == "NEW_NUMBER":
        employee = resolve_review_new_number(db, review, user.sub)
        db.commit()
        return IdentityReviewResolveResponse(status="NEW_NUMBER", unified_employee_number=employee.unified_employee_number)

    resolve_review_reject(db, review, user.sub)
    db.commit()
    return IdentityReviewResolveResponse(status="REJECTED", unified_employee_number=None)
