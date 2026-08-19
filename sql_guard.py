"""AST-based SQL validation for DataPilot."""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class SQLValidationError(RuntimeError):
    """Raised when generated SQL violates the read-only policy."""


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    sql: str = ""
    error: str = ""


class SQLGuard:
    """Allow one SQLite query and normalize its top-level row limit."""

    def __init__(self, max_rows: int = 100, dialect: str = "sqlite") -> None:
        if max_rows < 1:
            raise ValueError("max_rows 必须大于 0。")
        self.max_rows = max_rows
        self.dialect = dialect

    def validate(self, sql: str) -> ValidationResult:
        if not sql.strip():
            return ValidationResult(False, error="模型没有生成 SQL。")

        try:
            statements = sqlglot.parse(sql, read=self.dialect)
        except ParseError as exc:
            return ValidationResult(False, error=f"SQL 语法无效：{exc}")

        statements = [statement for statement in statements if statement is not None]
        if len(statements) != 1:
            return ValidationResult(False, error="仅允许执行一条 SQL 语句。")

        statement = statements[0]
        if not isinstance(statement, exp.Query):
            return ValidationResult(False, error="仅允许 SELECT 或 WITH 查询。")

        for function in statement.find_all(exp.Anonymous):
            if function.name.lower() == "load_extension":
                return ValidationResult(False, error="禁止调用 load_extension。")

        limit = statement.args.get("limit")
        if limit is None:
            statement = statement.limit(self.max_rows)
        else:
            expression = limit.expression
            if not isinstance(expression, exp.Literal) or not expression.is_int:
                return ValidationResult(False, error="LIMIT 必须是整数常量。")
            if int(expression.this) > self.max_rows:
                statement = statement.limit(self.max_rows)

        return ValidationResult(True, sql=statement.sql(dialect=self.dialect))

    def require_valid(self, sql: str) -> str:
        result = self.validate(sql)
        if not result.is_valid:
            raise SQLValidationError(result.error)
        return result.sql
