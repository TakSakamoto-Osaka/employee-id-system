"""共通入力検証 (spec 3): 個別登録・CSV一括・JSONバルクで共通のルールを適用する。"""
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, Organization


class FieldError(Exception):
    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__(str(errors))


@dataclass
class ValidatedInput:
    english_name: str
    date_of_birth: date
    existing_employee_number: str | None
    remarks: str | None
    company: Company
    organization: Organization | None
    job_title: str | None


def _err(field: str, code: str, message: str) -> dict:
    return {"field": field, "code": code, "message": message}


def validate_employee_input(db: Session, raw: dict) -> ValidatedInput:
    """Validates one employee record per spec section 3. Raises FieldError(422)."""
    errors: list[dict] = []

    english_name = (raw.get("english_name") or "").strip()
    if not english_name:
        errors.append(_err("english_name", "REQUIRED", "english_name is required"))
    elif len(english_name) > 200:
        errors.append(_err("english_name", "TOO_LONG", "english_name must be <= 200 characters"))

    dob_raw = raw.get("date_of_birth")
    dob: date | None = None
    if not dob_raw:
        errors.append(_err("date_of_birth", "REQUIRED", "date_of_birth is required"))
    else:
        try:
            dob = dob_raw if isinstance(dob_raw, date) else datetime.strptime(dob_raw, "%Y-%m-%d").date()
            if dob > datetime.utcnow().date():
                errors.append(_err("date_of_birth", "FUTURE_DATE", "date_of_birth cannot be in the future"))
        except ValueError:
            errors.append(_err("date_of_birth", "INVALID_FORMAT", "date_of_birth must be YYYY-MM-DD"))

    existing_number = raw.get("existing_employee_number") or None
    if existing_number is not None and len(existing_number) > 100:
        errors.append(_err("existing_employee_number", "TOO_LONG", "must be <= 100 characters"))

    remarks = raw.get("remarks") or None
    if remarks is not None and len(remarks) > 2000:
        errors.append(_err("remarks", "TOO_LONG", "remarks must be <= 2000 characters"))

    job_title = raw.get("job_title") or None
    if job_title is not None and len(job_title) > 200:
        errors.append(_err("job_title", "TOO_LONG", "job_title must be <= 200 characters"))

    company_code = raw.get("company_code")
    company: Company | None = None
    if not company_code:
        errors.append(_err("company_code", "REQUIRED", "company_code is required"))
    else:
        company = db.execute(
            select(Company).where(Company.code == company_code, Company.active.is_(True))
        ).scalar_one_or_none()
        if company is None:
            errors.append(_err("company_code", "UNKNOWN_COMPANY", "company_code is not a known active company"))

    organization_code = raw.get("organization_code")
    organization: Organization | None = None
    if organization_code and company is not None:
        organization = db.execute(
            select(Organization).where(
                Organization.code == organization_code,
                Organization.company_id == company.id,
                Organization.active.is_(True),
            )
        ).scalar_one_or_none()
        if organization is None:
            errors.append(
                _err(
                    "organization_code",
                    "UNKNOWN_ORGANIZATION",
                    "organization_code is not valid for the given company",
                )
            )

    if errors:
        raise FieldError(errors)

    return ValidatedInput(
        english_name=english_name,
        date_of_birth=dob,
        existing_employee_number=existing_number,
        remarks=remarks,
        company=company,
        organization=organization,
        job_title=job_title,
    )
