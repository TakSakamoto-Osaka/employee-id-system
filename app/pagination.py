"""簡易カーソルページング (spec 7.1: 既定50件・最大200件)。

オフセット値をbase64エンコードしたものをカーソルとして扱う。大規模本番運用
ではキーセットページングへの置き換えを推奨するが、機能要件は満たす。
"""
import base64


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception:
        return 0


def clamp_limit(limit: int, default: int = 50, maximum: int = 200) -> int:
    if limit <= 0:
        return default
    return min(limit, maximum)
