"""Idempotency-Key handling (spec 7.1, 7.4.2, 7.4.5).

同じ呼出元・キー・内容の再送には元の結果を返し、同じキーで内容が異なる
場合は 409 とする。保持期間は 7 日間 (暫定)。
"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import IdempotencyRecord

settings = get_settings()


def hash_request(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def find_existing(db: Session, caller_id: str, key: str, endpoint: str) -> IdempotencyRecord | None:
    stmt = select(IdempotencyRecord).where(
        IdempotencyRecord.caller_id == caller_id,
        IdempotencyRecord.idempotency_key == key,
        IdempotencyRecord.endpoint == endpoint,
    )
    return db.execute(stmt).scalar_one_or_none()


def check_or_conflict(
    db: Session, caller_id: str, key: str, endpoint: str, request_hash: str
) -> IdempotencyRecord | None:
    """Returns the stored record if this is a verified replay, or None if new.

    Raises 409 if the same key was previously used with different content.
    """
    existing = find_existing(db, caller_id, key, endpoint)
    if existing is None:
        return None
    if existing.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "IDEMPOTENCY_KEY_CONFLICT",
                "message": "Idempotency-Key was already used with different request content.",
                "field_errors": [],
            },
        )
    return existing


def store(
    db: Session,
    caller_id: str,
    key: str,
    endpoint: str,
    request_hash: str,
    status_code: int,
    response_body: dict,
) -> IdempotencyRecord:
    record = IdempotencyRecord(
        caller_id=caller_id,
        idempotency_key=key,
        endpoint=endpoint,
        request_hash=request_hash,
        status_code=status_code,
        response_body=response_body,
        expires_at=datetime.utcnow() + timedelta(days=settings.idempotency_ttl_days),
    )
    db.add(record)
    db.flush()
    return record
