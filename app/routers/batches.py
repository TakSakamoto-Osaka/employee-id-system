import json

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import (
    BatchStatus,
    Company,
    EmployeeBatch,
    EmployeeBatchRecord,
    IdentityReview,
    RowStatus,
)
from ..pagination import clamp_limit, decode_cursor, encode_cursor
from ..schemas import (
    BatchResultError,
    EmployeeBatchAcceptedResponse,
    EmployeeBatchCreateRequest,
    EmployeeBatchResultItem,
    EmployeeBatchResultsResponse,
    EmployeeBatchStatusResponse,
)
from ..security import CENTRAL_ADMIN, COMPANY_HR, API_ACCOUNT, CurrentUser, get_current_user, require_roles
from ..services.idempotency import check_or_conflict, hash_request, store
from ..workers.batch_worker import process_batch

router = APIRouter(prefix="/api/v1/employee-batches", tags=["employee-batches"])
settings = get_settings()


@router.post("", response_model=EmployeeBatchAcceptedResponse, status_code=202)
def create_batch(
    payload: EmployeeBatchCreateRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(CENTRAL_ADMIN, COMPANY_HR, API_ACCOUNT)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail={"code": "MISSING_IDEMPOTENCY_KEY", "message": "Idempotency-Key header is required", "field_errors": []})

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.batch_max_bytes:
        raise HTTPException(status_code=413, detail={"code": "PAYLOAD_TOO_LARGE", "message": "request body exceeds size limit", "field_errors": []})

    if len(payload.employees) > settings.batch_max_records:
        raise HTTPException(status_code=413, detail={"code": "TOO_MANY_RECORDS", "message": f"employees exceeds limit of {settings.batch_max_records}", "field_errors": []})

    client_ids = [e.client_record_id for e in payload.employees]
    if len(client_ids) != len(set(client_ids)):
        raise HTTPException(status_code=422, detail={"code": "DUPLICATE_CLIENT_RECORD_ID", "message": "client_record_id must be unique within the batch", "field_errors": []})

    raw = payload.model_dump()
    req_hash = hash_request(raw)
    existing = check_or_conflict(db, user.sub, idempotency_key, "POST /employee-batches", req_hash)
    if existing is not None:
        response.headers["Location"] = existing.response_body.get("status_url", "")
        return existing.response_body

    batch = EmployeeBatch(caller_id=user.sub, status=BatchStatus.QUEUED.value, total_count=len(payload.employees))
    db.add(batch)
    db.flush()

    for idx, item in enumerate(payload.employees, start=1):
        record_data = item.model_dump(exclude={"client_record_id"})
        db.add(
            EmployeeBatchRecord(
                batch_id=batch.id,
                record_index=idx,
                client_record_id=item.client_record_id,
                input_data=record_data,
                status=RowStatus.PENDING.value,
            )
        )

    status_url = f"/api/v1/employee-batches/{batch.id}"
    results_url = f"/api/v1/employee-batches/{batch.id}/results"
    body = {
        "batch_id": batch.id,
        "status": batch.status,
        "total_count": batch.total_count,
        "status_url": status_url,
        "results_url": results_url,
    }
    store(db, user.sub, idempotency_key, "POST /employee-batches", req_hash, 202, body)
    db.commit()

    response.headers["Location"] = status_url
    background_tasks.add_task(process_batch, batch.id)
    return body


def _load_batch(db: Session, batch_id: str, user: CurrentUser) -> EmployeeBatch:
    batch = db.get(EmployeeBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "batch not found", "field_errors": []})
    if batch.caller_id != user.sub and not user.has_role(CENTRAL_ADMIN):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "no access to this batch", "field_errors": []})
    return batch


@router.get("/{batch_id}", response_model=EmployeeBatchStatusResponse)
def get_batch_status(batch_id: str, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    batch = _load_batch(db, batch_id, user)
    return EmployeeBatchStatusResponse(
        batch_id=batch.id,
        status=batch.status,
        total_count=batch.total_count,
        processed_count=batch.processed_count,
        created_count=batch.created_count,
        existing_count=batch.existing_count,
        review_required_count=batch.review_required_count,
        error_count=batch.error_count,
        cancelled_count=batch.cancelled_count,
        pending_count=batch.pending_count,
        created_at=batch.created_at,
        started_at=batch.started_at,
        finished_at=batch.finished_at,
    )


@router.get("/{batch_id}/results", response_model=EmployeeBatchResultsResponse)
def get_batch_results(
    batch_id: str,
    status_filter: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    batch = _load_batch(db, batch_id, user)
    offset = decode_cursor(cursor)
    limit = clamp_limit(limit)

    stmt = select(EmployeeBatchRecord).where(
        EmployeeBatchRecord.batch_id == batch.id,
        EmployeeBatchRecord.status != RowStatus.PENDING.value,
    )
    if status_filter:
        stmt = stmt.where(EmployeeBatchRecord.status == status_filter)

    if not user.has_role(CENTRAL_ADMIN) and "*" not in user.companies:
        accessible = set(user.companies)

        def _company_ok(record: EmployeeBatchRecord) -> bool:
            code = record.input_data.get("company_code")
            return code in accessible

    else:
        def _company_ok(record: EmployeeBatchRecord) -> bool:
            return True

    stmt = stmt.order_by(EmployeeBatchRecord.record_index.asc())
    all_rows = [r for r in db.execute(stmt).scalars().all() if _company_ok(r)]

    page = all_rows[offset: offset + limit]
    has_more = len(all_rows) > offset + limit

    items = []
    for r in page:
        error = None
        if r.status == RowStatus.ERROR.value:
            field_errors = []
            try:
                parsed = json.loads(r.error_message) if r.error_message else []
                if isinstance(parsed, list):
                    field_errors = parsed
            except (json.JSONDecodeError, TypeError):
                pass
            error = BatchResultError(code=r.error_code or "ERROR", message="validation or processing error", field_errors=field_errors)
        items.append(
            EmployeeBatchResultItem(
                record_index=r.record_index,
                client_record_id=r.client_record_id,
                status=r.status,
                unified_employee_number=r.unified_employee_number,
                review_id=r.review_id,
                error=error,
            )
        )

    next_cursor = encode_cursor(offset + limit) if has_more else None
    return EmployeeBatchResultsResponse(batch_id=batch.id, items=items, next_cursor=next_cursor)


@router.post("/{batch_id}/cancel")
def cancel_batch(batch_id: str, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    batch = _load_batch(db, batch_id, user)
    if batch.status in (BatchStatus.COMPLETED.value, BatchStatus.FAILED.value, BatchStatus.CANCELLED.value):
        return Response(status_code=200, content=json.dumps({"batch_id": batch.id, "status": batch.status}), media_type="application/json")

    batch.cancel_requested = True
    db.commit()
    return Response(status_code=202, content=json.dumps({"batch_id": batch.id, "status": batch.status}), media_type="application/json")
