"""CSV一括登録の非同期ワーカー (spec 6)。

事前検証 (validate_import_job) では採番・登録を行わず、件数の見込みのみを
計算する。実行 (execute_import_job) では共通登録サービスを使って行ごとに
独立したトランザクションで確定する。ジョブID・行番号の一意制約により、
再実行時も確定済み行を二重登録しない。
"""
import csv
import io
from datetime import datetime

from sqlalchemy import select

from ..database import SessionLocal
from ..models import ImportJob, ImportJobStatus, ImportRow, RowStatus
from ..services.employees import preview_registration, register_employee
from ..services.validation import FieldError

EXPECTED_HEADER = [
    "english_name",
    "date_of_birth",
    "existing_employee_number",
    "remarks",
    "company_code",
    "organization_code",
    "job_title",
]


def _parse_csv(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def validate_import_job(job_id: str, file_path: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(ImportJob, job_id)
        if job is None:
            return
        job.status = ImportJobStatus.VALIDATING.value
        db.commit()

        with open(file_path, "rb") as f:
            content = f.read()

        try:
            rows = _parse_csv(content)
        except Exception:
            job.status = ImportJobStatus.FAILED.value
            job.finished_at = datetime.utcnow()
            db.commit()
            return

        new_count = existing_count = review_count = error_count = 0

        for idx, raw_row in enumerate(rows, start=1):
            row = ImportRow(job_id=job.id, row_number=idx, input_data=raw_row, status=RowStatus.PENDING.value)
            try:
                classification = preview_registration(db, raw_row)
                if classification == "CREATED":
                    new_count += 1
                elif classification == "EXISTING":
                    existing_count += 1
                else:
                    review_count += 1
            except FieldError as exc:
                row.status = RowStatus.ERROR.value
                row.error_code = "VALIDATION_ERROR"
                row.error_message = "; ".join(f"{e['field']}:{e['code']}" for e in exc.errors)[:500]
                error_count += 1
            db.add(row)
            db.commit()

        job = db.get(ImportJob, job_id)
        job.total_count = len(rows)
        job.preview_new_count = new_count
        job.preview_existing_count = existing_count
        job.preview_review_count = review_count
        job.error_count = error_count
        job.status = ImportJobStatus.READY.value
        db.commit()
    except Exception:
        db.rollback()
        job = db.get(ImportJob, job_id)
        if job is not None:
            job.status = ImportJobStatus.FAILED.value
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def execute_import_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(ImportJob, job_id)
        if job is None:
            return
        if job.status not in (ImportJobStatus.READY.value, ImportJobStatus.RUNNING.value):
            return

        job.status = ImportJobStatus.RUNNING.value
        job.started_at = datetime.utcnow()
        db.commit()

        pending_rows = db.execute(
            select(ImportRow)
            .where(ImportRow.job_id == job.id, ImportRow.status == RowStatus.PENDING.value)
            .order_by(ImportRow.row_number.asc())
        ).scalars().all()

        for row in pending_rows:
            db.refresh(job)
            if job.cancel_requested:
                row.status = RowStatus.CANCELLED.value
                row.processed_at = datetime.utcnow()
                job.cancelled_count += 1
                db.commit()
                continue
            _execute_one(db, job, row)

        db.refresh(job)
        job.status = ImportJobStatus.CANCELLED.value if job.cancel_requested else ImportJobStatus.COMPLETED.value
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        job = db.get(ImportJob, job_id)
        if job is not None:
            job.status = ImportJobStatus.FAILED.value
            job.finished_at = datetime.utcnow()
            db.commit()
        raise
    finally:
        db.close()


def _execute_one(db, job: ImportJob, row: ImportRow) -> None:
    try:
        result = register_employee(db, row.input_data, actor=f"import:{job.executed_by}")
        if result.status == "CREATED":
            row.status = RowStatus.CREATED.value
            row.employee_id = result.employee.id
            row.unified_employee_number = result.employee.unified_employee_number
            job.created_count += 1
        elif result.status == "EXISTING":
            row.status = RowStatus.EXISTING.value
            row.employee_id = result.employee.id
            row.unified_employee_number = result.employee.unified_employee_number
            job.existing_count += 1
        else:
            row.status = RowStatus.REVIEW_REQUIRED.value
            row.review_id = result.review.id
            job.review_count += 1
        row.processed_at = datetime.utcnow()
        db.commit()
    except FieldError as exc:
        db.rollback()
        row = db.get(ImportRow, row.id)
        row.status = RowStatus.ERROR.value
        row.error_code = "VALIDATION_ERROR"
        row.error_message = "; ".join(f"{e['field']}:{e['code']}" for e in exc.errors)[:500]
        row.processed_at = datetime.utcnow()
        job = db.get(ImportJob, job.id)
        job.error_count += 1
        db.commit()
    except Exception:
        db.rollback()
        row = db.get(ImportRow, row.id)
        row.status = RowStatus.ERROR.value
        row.error_code = "INTERNAL_ERROR"
        row.error_message = "Unexpected error while processing this row."
        row.processed_at = datetime.utcnow()
        job = db.get(ImportJob, job.id)
        job.error_count += 1
        db.commit()
