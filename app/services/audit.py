from sqlalchemy.orm import Session

from ..models import AuditLog


def record(
    db: Session,
    actor: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    details: dict | None = None,
    request_id: str | None = None,
) -> None:
    """Spec 10: 社員詳細閲覧、検索、登録、変更、確認判断、統合を監査対象とする。

    details には必要最小限の変更内容のみを記録し、生年月日・備考等の本文は
    含めない (spec 10)。
    """
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            request_id=request_id,
        )
    )
    db.flush()
