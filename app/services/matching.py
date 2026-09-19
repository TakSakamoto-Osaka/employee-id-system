from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Employee, EmployeeAffiliation


def find_existing_mapping(db: Session, company_id: str, existing_employee_number: str) -> EmployeeAffiliation | None:
    stmt = select(EmployeeAffiliation).where(
        EmployeeAffiliation.company_id == company_id,
        EmployeeAffiliation.existing_employee_number == existing_employee_number,
    )
    return db.execute(stmt).scalar_one_or_none()


def find_name_dob_candidates(db: Session, normalized_name: str, date_of_birth) -> list[Employee]:
    stmt = select(Employee).where(
        Employee.english_name_normalized == normalized_name,
        Employee.date_of_birth == date_of_birth,
    )
    return list(db.execute(stmt).scalars().all())
