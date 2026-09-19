"""英語名称の正規化 (spec 3.1).

原文は保持し、照合用値は別カラムに保存する。
NFKC正規化、前後空白除去、連続空白の単一化、大文字化のみを行う。
アポストロフィー・ハイフン・ダイアクリティカルマークは削除しない。
姓名の並べ替えや略称への自動変換は行わない。
"""
import re
import unicodedata

NORMALIZATION_VERSION = 1

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_english_name(raw_name: str) -> str:
    value = unicodedata.normalize("NFKC", raw_name)
    value = value.strip()
    value = _WHITESPACE_RE.sub(" ", value)
    return value.upper()
