"""社員登録・照合・採番の共通サービス (spec 4.2, 4.3).

Web個別登録・CSV一括登録・JSONバルク登録のすべてがこのサービスを利用する
(spec 4.2 "Web・API・一括登録は同じ登録サービスを利用する。" / 7.4 "照合・採番は
個別登録・CSV登録と同じ共通サービスを使用する。")
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Employee, EmployeeAffiliation, IdentityReview, ReviewStatus
from . import audit
from .locking import acquire_match_lock, matching_key
from .matching import find_existing_mapping, find_name_dob_candidates
from .normalization import NORMALIZATION_VERSION, normalize_english_name
from .numbering import next_unified_employee_number
from .validation import ValidatedInput, validate_employee_input


@dataclass
class RegistrationResult:
    status: str  # CREATED | EXISTING | REVIEW_REQUIRED
    employee: Employee | None = None
    review: IdentityReview | None = None


def _create_employee_and_affiliation(
    db: Session, validated: ValidatedInput, normalized_name: str, actor: str
) -> Employee:
    number = next_unified_employee_number(db)
    employee = Employee(
        unified_employee_number=number,
        english_name_original=validated.english_name,
        english_name_normalized=normalized_name,
        normalization_version=NORMALIZATION_VERSION,
        date_of_birth=validated.date_of_birth,
        created_by=actor,
        updated_by=actor,
    )
    db.add(employee)
    db.flush()

    affiliation = EmployeeAffiliation(
        employee_id=employee.id,
        company_id=validated.company.id,
        organization_id=validated.organization.id if validated.organization else None,
        existing_employee_number=validated.existing_employee_number,
        job_title=validated.job_title,
        remarks=validated.remarks,
    )
    db.add(affiliation)
    db.flush()

    audit.record(
        db,
        actor=actor,
        action="EMPLOYEE_CREATED",
        target_type="employee",
        target_id=employee.id,
        details={"company_id": validated.company.id, "unified_employee_number": number},
    )
    return employee


def _create_review(
    db: Session,
    raw: dict,
    company_id: str | None,
    candidate_employee_id: str | None,
    reason: str,
) -> IdentityReview:
    review = IdentityReview(
        input_data=raw,
        candidate_employee_id=candidate_employee_id,
        company_id=company_id,
        reason=reason,
        status=ReviewStatus.PENDING.value,
    )
    db.add(review)
    db.flush()
    audit.record(
        db,
        actor="system",
        action="IDENTITY_REVIEW_CREATED",
        target_type="identity_review",
        target_id=review.id,
        details={"reason": reason},
    )
    return review


def preview_registration(db: Session, raw: dict) -> str:
    """Read-only classification for CSV pre-validation (spec 6.2 step 2).

    Returns one of CREATED, EXISTING, REVIEW_REQUIRED without persisting
    anything or consuming a unified employee number. Raises FieldError on
    invalid input, matching the real registration path.
    """
    validated = validate_employee_input(db, raw)
    normalized_name = normalize_english_name(validated.english_name)

    if validated.existing_employee_number:
        mapping = find_existing_mapping(db, validated.company.id, validated.existing_employee_number)
        if mapping is not None:
            employee = db.get(Employee, mapping.employee_id)
            if (
                employee.english_name_normalized == normalized_name
                and employee.date_of_birth == validated.date_of_birth
            ):
                return "EXISTING"
            return "REVIEW_REQUIRED"

    candidates = find_name_dob_candidates(db, normalized_name, validated.date_of_birth)
    return "CREATED" if not candidates else "REVIEW_REQUIRED"


def register_employee(db: Session, raw: dict, actor: str) -> RegistrationResult:
    """Implements spec 4.2 steps 3-7. Raises FieldError on invalid input (-> 422)."""
    validated = validate_employee_input(db, raw)
    normalized_name = normalize_english_name(validated.english_name)

    key = matching_key(normalized_name, validated.date_of_birth)
    acquire_match_lock(db, key)

    # Step 3-5: check existing company + existing_employee_number mapping.
    if validated.existing_employee_number:
        mapping = find_existing_mapping(
            db, validated.company.id, validated.existing_employee_number
        )
        if mapping is not None:
            employee = db.get(Employee, mapping.employee_id)
            if (
                employee.english_name_normalized == normalized_name
                and employee.date_of_birth == validated.date_of_birth
            ):
                audit.record(
                    db,
                    actor=actor,
                    action="EMPLOYEE_MATCHED_EXISTING",
                    target_type="employee",
                    target_id=employee.id,
                )
                return RegistrationResult(status="EXISTING", employee=employee)
            review = _create_review(
                db,
                raw,
                company_id=validated.company.id,
                candidate_employee_id=employee.id,
                reason="EXISTING_NUMBER_CONFLICT",
            )
            return RegistrationResult(status="REVIEW_REQUIRED", review=review)

    # Step 6-7: no reliable existing mapping -> search name+DOB candidates.
    candidates = find_name_dob_candidates(db, normalized_name, validated.date_of_birth)
    if not candidates:
        employee = _create_employee_and_affiliation(db, validated, normalized_name, actor)
        return RegistrationResult(status="CREATED", employee=employee)

    review = _create_review(
        db,
        raw,
        company_id=validated.company.id,
        candidate_employee_id=candidates[0].id,
        reason="NAME_DOB_CANDIDATE",
    )
    return RegistrationResult(status="REVIEW_REQUIRED", review=review)


def resolve_review_link(db: Session, review: IdentityReview, target_employee: Employee, actor: str) -> Employee:
    """4.2 step 7: 既存社員への関連付け。"""
    validated = validate_employee_input(db, review.input_data)
    affiliation = EmployeeAffiliation(
        employee_id=target_employee.id,
        company_id=validated.company.id,
        organization_id=validated.organization.id if validated.organization else None,
        existing_employee_number=validated.existing_employee_number,
        job_title=validated.job_title,
        remarks=validated.remarks,
    )
    db.add(affiliation)
    review.status = ReviewStatus.LINKED.value
    review.resolution_employee_id = target_employee.id
    review.resolved_by = actor
    review.resolved_at = datetime.utcnow()
    db.flush()
    audit.record(
        db,
        actor=actor,
        action="IDENTITY_REVIEW_LINKED",
        target_type="identity_review",
        target_id=review.id,
        details={"employee_id": target_employee.id},
    )
    return target_employee


def resolve_review_new_number(db: Session, review: IdentityReview, actor: str) -> Employee:
    """4.2 step 7: 別人としての新規採番。"""
    validated = validate_employee_input(db, review.input_data)
    normalized_name = normalize_english_name(validated.english_name)
    employee = _create_employee_and_affiliation(db, validated, normalized_name, actor)
    review.status = ReviewStatus.NEW_NUMBER.value
    review.resolution_employee_id = employee.id
    review.resolved_by = actor
    review.resolved_at = datetime.utcnow()
    db.flush()
    audit.record(
        db,
        actor=actor,
        action="IDENTITY_REVIEW_NEW_NUMBER",
        target_type="identity_review",
        target_id=review.id,
        details={"employee_id": employee.id},
    )
    return employee


def resolve_review_reject(db: Session, review: IdentityReview, actor: str) -> None:
    review.status = ReviewStatus.REJECTED.value
    review.resolved_by = actor
    review.resolved_at = datetime.utcnow()
    db.flush()
    audit.record(
        db,
        actor=actor,
        action="IDENTITY_REVIEW_REJECTED",
        target_type="identity_review",
        target_id=review.id,
    )
