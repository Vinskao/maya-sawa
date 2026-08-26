"""Research pipeline 共用錯誤型別。"""

from __future__ import annotations


class SchemaError(ValueError):
    """結構解析失敗，attach 可讀的錯誤列表。"""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors) or "schema error")
