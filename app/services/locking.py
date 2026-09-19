"""照合キー単位のロック (spec 4.2): 照合から確定までを直列化する。

同一トランザクション内で match_locks 行を SELECT ... FOR UPDATE することで、
同じ (正規化名, 生年月日) キーに対する複数の同時登録リクエストを直列化する。
SQLite (テスト用) は FOR UPDATE をサポートしないため、その場合はプレーンな
SELECT にフォールバックする (テストは単一スレッドで実行されるため安全)。
"""
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MatchLock


def matching_key(normalized_name: str, date_of_birth) -> str:
    raw = f"{normalized_name}|{date_of_birth.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def acquire_match_lock(db: Session, key: str) -> None:
    existing = db.get(MatchLock, key)
    if existing is None:
        db.add(MatchLock(key=key))
        db.flush()

    is_sqlite = db.bind.dialect.name == "sqlite" if db.bind is not None else True
    stmt = select(MatchLock).where(MatchLock.key == key)
    if not is_sqlite:
        stmt = stmt.with_for_update()
    db.execute(stmt).scalar_one()
