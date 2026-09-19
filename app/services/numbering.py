"""統一社員番号の採番・検証 (spec 4.1).

形式: 'E' + 数字7桁の連番 + Luhn(モジュラス10)チェックデジット1桁 = 9文字。
連番は 0000001-9999999。0000000 は予約値として採番しない。
"""
import re

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Counter

NUMBER_PATTERN = re.compile(r"^E[0-9]{8}$")
MAX_SEQUENCE = 9_999_999
COUNTER_NAME = "employee_number"


def compute_check_digit(seven_digits: str) -> str:
    """Luhn (mod 10) check digit for a 7-digit sequence, per spec 4.1."""
    if len(seven_digits) != 7 or not seven_digits.isdigit():
        raise ValueError("seven_digits must be exactly 7 numeric characters")

    total = 0
    # Rightmost digit is position 1. Positions 1,3,5,7 are doubled.
    for idx, ch in enumerate(reversed(seven_digits)):
        position = idx + 1
        digit = int(ch)
        if position % 2 == 1:
            digit *= 2
            if digit >= 10:
                digit -= 9
        total += digit

    return str((10 - (total % 10)) % 10)


def build_unified_number(sequence: int) -> str:
    if sequence < 1 or sequence > MAX_SEQUENCE:
        raise ValueError("sequence out of range 1..9999999")
    seven = f"{sequence:07d}"
    check_digit = compute_check_digit(seven)
    return f"E{seven}{check_digit}"


def validate_unified_number(number: str) -> bool:
    """Format + check digit validation per spec 4.1 / acceptance criteria 13."""
    if not NUMBER_PATTERN.match(number or ""):
        return False
    seven = number[1:8]
    check_digit = number[8]
    total = 0
    for idx, ch in enumerate(reversed(seven)):
        position = idx + 1
        digit = int(ch)
        if position % 2 == 1:
            digit *= 2
            if digit >= 10:
                digit -= 9
        total += digit
    return (total + int(check_digit)) % 10 == 0


class SequenceExhaustedError(RuntimeError):
    pass


def ensure_counter_initialized(db: Session) -> None:
    existing = db.get(Counter, COUNTER_NAME)
    if existing is None:
        db.add(Counter(name=COUNTER_NAME, value=0))
        db.flush()


def next_unified_employee_number(db: Session) -> str:
    """Atomically increments the shared counter and returns a new number.

    Uses an UPDATE ... RETURNING against a dedicated counter row instead of
    MAX(unified_employee_number)+1 (explicitly disallowed by spec 4.1), so
    concurrent transactions serialize on the counter row rather than racing.
    The unique constraint on employees.unified_employee_number is a second
    line of defense.
    """
    ensure_counter_initialized(db)

    stmt = (
        update(Counter)
        .where(Counter.name == COUNTER_NAME)
        .values(value=Counter.value + 1)
        .returning(Counter.value)
    )
    result = db.execute(stmt)
    new_value = result.scalar_one()

    if new_value > MAX_SEQUENCE:
        raise SequenceExhaustedError(
            "統一社員番号の採番可能数の上限に達しました。管理者へ通知してください。"
        )

    return build_unified_number(new_value)
