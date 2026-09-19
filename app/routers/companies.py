from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Company, Organization
from ..schemas import (
    CompanyCreateRequest,
    CompanyOut,
    OrganizationCreateRequest,
    OrganizationOut,
)
from ..security import CENTRAL_ADMIN, CurrentUser, get_current_user, require_roles

router = APIRouter(prefix="/api/v1", tags=["masters"])


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(
    db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
) -> list[CompanyOut]:
    companies = db.execute(select(Company).where(Company.active.is_(True))).scalars().all()
    return [CompanyOut.model_validate(c) for c in companies]


@router.post("/companies", response_model=CompanyOut, status_code=201)
def create_company(
    payload: CompanyCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(CENTRAL_ADMIN)),
) -> CompanyOut:
    company = Company(code=payload.code, name=payload.name, active=True)
    db.add(company)
    db.commit()
    db.refresh(company)
    return CompanyOut.model_validate(company)


@router.get("/organizations", response_model=list[OrganizationOut])
def list_organizations(
    company_code: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[OrganizationOut]:
    stmt = select(Organization).where(Organization.active.is_(True))
    if company_code:
        stmt = stmt.join(Company).where(Company.code == company_code)
    orgs = db.execute(stmt).scalars().all()
    result = []
    for org in orgs:
        parent_code = None
        if org.parent_organization_id:
            parent = db.get(Organization, org.parent_organization_id)
            parent_code = parent.code if parent else None
        result.append(
            OrganizationOut(
                code=org.code,
                name=org.name,
                company_code=org.company.code,
                parent_organization_code=parent_code,
                active=org.active,
            )
        )
    return result


@router.post("/organizations", response_model=OrganizationOut, status_code=201)
def create_organization(
    payload: OrganizationCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(CENTRAL_ADMIN)),
) -> OrganizationOut:
    company = db.execute(select(Company).where(Company.code == payload.company_code)).scalar_one()
    parent_id = None
    if payload.parent_organization_code:
        parent = db.execute(
            select(Organization).where(
                Organization.code == payload.parent_organization_code,
                Organization.company_id == company.id,
            )
        ).scalar_one()
        parent_id = parent.id

    org = Organization(
        code=payload.code,
        name=payload.name,
        company_id=company.id,
        parent_organization_id=parent_id,
        active=True,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return OrganizationOut(
        code=org.code,
        name=org.name,
        company_code=company.code,
        parent_organization_code=payload.parent_organization_code,
        active=org.active,
    )
