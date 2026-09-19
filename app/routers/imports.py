import csv
import io
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import ImportJob, ImportJobStatus, ImportRow, RowStatus
from ..pagination import clamp_limit, decode_cursor, encode_cursor
from ..schemas import (
    ImportJobCreatedResponse,
    ImportJobResultsResponse,
    ImportJobStatusResponse,
    ImportRowResult,
)
from ..security import CENTRAL_ADMIN, COMPANY_HR, CurrentUser, require_roles
from ..workers.csv_worker import EXPECTED_HEADER, execute_import_job, validate_import_job

router = APIRouter(prefix="/api/v1/employee-imports", tags=["employee-imports"])
settings = get_settings()

os.makedirs(settings.import_storage_dir, exist_ok=True)


def _formula_safe(value: str | None) -> str:
    """CSV出力の数式インジェクション対策 (spec 6.2)。"""
    if value and value[0] in ("=", "+", "-", "@"):
        return "'" + value
    return value or ""


@router.get("/template")
def download_template(user: CurrentUser = Depends(require_roles(CENTRAL_ADMIN, COMPANY_HR))):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPECTED_HEADER)
    writer.writerow(["TARO YAMADA", "1990-04-15", "000123", "", "JP001", "SALES01", "Manager"])
    return Response(content=buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=template.csv"})


@router.post("", response_model=ImportJobCreatedResponse, status_code=202)
async def upload_import(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(CENTRAL_ADMIN, COMPANY_HR)),
):
    content = await file.read()
    if len(content) > settings.csv_max_bytes:
        raise HTTPException(status_code=413, detail={"code": "FILE_TOO_LARGE", "message": "file exceeds size limit", "field_errors": []})

    row_count_estimate = content.count(b"\n")
    if row_count_estimate > settings.csv_max_rows + 1:
        raise HTTPException(status_code=413, detail={"code": "TOO_MANY_ROWS", "message": "file exceeds row limit", "field_errors": []})

    job_id = str(uuid.uuid4())
    file_path = os.path.join(settings.import_storage_dir, f"{job_id}.csv")
    with open(file_path, "wb") as f:
        f.write(content)

    job = ImportJob(
        id=job_id,
        file_reference=file_path,
        original_filename=file.filename or "upload.csv",
        executed_by=user.sub,
        status=ImportJobStatus.UPLOADED.value,
    )
    db.add(job)
    db.commit()

    background_tasks.add_task(validate_import_job, job_id, file_path)
    return {"job_id": job_id, "status": job.status}


def _load_job(db: Session, job_id: str, user: CurrentUser) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "job not found", "field_errors": []})
    if job.executed_by != user.sub and not user.has_role(CENTRAL_ADMIN):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "no access to this job", "field_errors": []})
    return job


@router.get("/{job_id}", response_model=ImportJobStatusResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require_roles(CENTRAL_ADMIN, COMPANY_HR))):
    job = _load_job(db, job_id, user)
    return ImportJobStatusResponse(
        job_id=job.id,
        status=job.status,
        total_count=job.total_count,
        created_count=job.created_count,
        existing_count=job.existing_count,
        review_count=job.review_count,
        error_count=job.error_count,
        cancelled_count=job.cancelled_count,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post("/{job_id}/execute", status_code=202)
def execute_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(CENTRAL_ADMIN, COMPANY_HR)),
):
    job = _load_job(db, job_id, user)
    if job.status not in (ImportJobStatus.READY.value, ImportJobStatus.RUNNING.value, ImportJobStatus.COMPLETED.value):
        raise HTTPException(status_code=409, detail={"code": "INVALID_STATE", "message": f"job is in state {job.status}", "field_errors": []})

    # Re-execution of a completed job returns the existing result (spec 6.2).
    if job.status == ImportJobStatus.COMPLETED.value:
        return {"job_id": job.id, "status": job.status}

    background_tasks.add_task(execute_import_job, job_id)
    return {"job_id": job.id, "status": "RUNNING"}


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require_roles(CENTRAL_ADMIN, COMPANY_HR))):
    job = _load_job(db, job_id, user)
    if job.status in (ImportJobStatus.COMPLETED.value, ImportJobStatus.FAILED.value, ImportJobStatus.CANCELLED.value):
        return {"job_id": job.id, "status": job.status}
    job.cancel_requested = True
    db.commit()
    return {"job_id": job.id, "status": job.status}


@router.get("/{job_id}/results")
def get_results(
    job_id: str,
    format: str = "json",
    status_filter: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(CENTRAL_ADMIN, COMPANY_HR)),
):
    job = _load_job(db, job_id, user)
    stmt = select(ImportRow).where(ImportRow.job_id == job.id)
    if status_filter:
        stmt = stmt.where(ImportRow.status == status_filter)
    stmt = stmt.order_by(ImportRow.row_number.asc())

    if format == "csv":
        rows = db.execute(stmt).scalars().all()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["row_number", "status", "unified_employee_number", "error_code", "reason", "review_id"])
        for r in rows:
            writer.writerow([
                r.row_number,
                r.status,
                _formula_safe(r.unified_employee_number),
                _formula_safe(r.error_code),
                _formula_safe(r.error_message),
                _formula_safe(r.review_id),
            ])
        return Response(content=buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=result-{job_id}.csv"})

    offset = decode_cursor(cursor)
    limit = clamp_limit(limit)
    rows = db.execute(stmt.offset(offset).limit(limit + 1)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        ImportRowResult(
            row_number=r.row_number,
            status=r.status,
            unified_employee_number=r.unified_employee_number,
            review_id=r.review_id,
            error_code=r.error_code,
            error_message=r.error_message,
        )
        for r in rows
    ]
    next_cursor = encode_cursor(offset + limit) if has_more else None
    return ImportJobResultsResponse(job_id=job.id, items=items, next_cursor=next_cursor)
