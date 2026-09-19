import pytest

from app.services.numbering import build_unified_number, compute_check_digit, validate_unified_number


@pytest.mark.parametrize(
    "seven_digits,expected_check_digit,expected_number",
    [
        ("0000001", "8", "E00000018"),
        ("0000002", "6", "E00000026"),
        ("1234567", "4", "E12345674"),
    ],
)
def test_check_digit_matches_spec_examples(seven_digits, expected_check_digit, expected_number):
    assert compute_check_digit(seven_digits) == expected_check_digit
    assert build_unified_number(int(seven_digits)) == expected_number


def test_validate_unified_number_accepts_valid_numbers():
    assert validate_unified_number("E00000018") is True
    assert validate_unified_number("E12345674") is True


def test_validate_unified_number_rejects_bad_check_digit():
    assert validate_unified_number("E00000019") is False


def test_validate_unified_number_rejects_bad_format():
    assert validate_unified_number("E0000001") is False  # too short
    assert validate_unified_number("X000000018") is False  # wrong prefix
    assert validate_unified_number("") is False


def test_check_digit_round_trips_for_arbitrary_sequence():
    digit = compute_check_digit("0000009")
    number = f"E0000009{digit}"
    assert validate_unified_number(number) is True


def test_build_unified_number_rejects_out_of_range_sequence():
    with pytest.raises(ValueError):
        build_unified_number(0)
    with pytest.raises(ValueError):
        build_unified_number(10_000_000)
