"""JSONバルク登録の非同期ワーカー (spec 7.4).

本実装では FastAPI の BackgroundTasks (スレッドプール実行) を簡易ワーカーと
して用いる。実運用では Celery/RQ 等の独立したジョブキュー・ワーカープロセス
に置き換える (spec 13: 実装前に確定する事項)。各行は独立したトランザクション
で確定し、バッチ全体の一括ロールバックは行わない (spec 7.4.3)。
"""
import json
from datetime import datetime

from sqlalchemy import select

from ..database import SessionLocal
from ..models import BatchStatus, EmployeeBatch, EmployeeBatchRecord, RowStatus
from ..services.employees import register_employee
from ..services.validation import FieldError


def process_batch(batch_id: str) -> None:
    db = SessionLocal()
    try:
        batch = db.get(EmployeeBatch, batch_id)
        if batch is None:
            return

        batch.status = BatchStatus.RUNNING.value
        batch.started_at = datetime.utcnow()
        db.commit()

        records = db.execute(
            select(EmployeeBatchRecord)
            .where(
                EmployeeBatchRecord.batch_id == batch_id,
                EmployeeBatchRecord.status == RowStatus.PENDING.value,
            )
            .order_by(EmployeeBatchRecord.record_index.asc())
        ).scalars().all()

        for record in records:
            db.refresh(batch)
            if batch.cancel_requested:
                record.status = RowStatus.CANCELLED.value
                record.processed_at = datetime.utcnow()
                batch.cancelled_count += 1
                db.commit()
                continue

            _process_one(db, batch, record)

        db.refresh(batch)
        batch.status = (
            BatchStatus.CANCELLED.value if batch.cancel_requested else BatchStatus.COMPLETED.value
        )
        batch.finished_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        batch = db.get(EmployeeBatch, batch_id)
        if batch is not None:
            batch.status = BatchStatus.FAILED.value
            batch.finished_at = datetime.utcnow()
            db.commit()
        raise
    finally:
        db.close()


def _process_one(db, batch: EmployeeBatch, record: EmployeeBatchRecord) -> None:
    try:
        result = register_employee(db, record.input_data, actor=f"batch:{batch.caller_id}")
        if result.status == "CREATED":
            record.status = RowStatus.CREATED.value
            record.employee_id = result.employee.id
            record.unified_employee_number = result.employee.unified_employee_number
            batch.created_count += 1
        elif result.status == "EXISTING":
            record.status = RowStatus.EXISTING.value
            record.employee_id = result.employee.id
            record.unified_employee_number = result.employee.unified_employee_number
            batch.existing_count += 1
        else:
            record.status = RowStatus.REVIEW_REQUIRED.value
            record.review_id = result.review.id
            batch.review_required_count += 1
        record.processed_at = datetime.utcnow()
        db.commit()
    except FieldError as exc:
        db.rollback()
        record = db.get(EmployeeBatchRecord, record.id)
        record.status = RowStatus.ERROR.value
        record.error_code = "VALIDATION_ERROR"
        record.error_message = json.dumps(exc.errors)[:500]
        record.processed_at = datetime.utcnow()
        batch = db.get(EmployeeBatch, batch.id)
        batch.error_count += 1
        db.commit()
    except Exception as exc:  # unexpected per-row failure must not abort the batch
        db.rollback()
        record = db.get(EmployeeBatchRecord, record.id)
        record.status = RowStatus.ERROR.value
        record.error_code = "INTERNAL_ERROR"
        record.error_message = "Unexpected error while processing this record."
        record.processed_at = datetime.utcnow()
        batch = db.get(EmployeeBatch, batch.id)
        batch.error_count += 1
        db.commit()
