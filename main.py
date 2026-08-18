"""Command-line entry point for DataPilot V0."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent import DataPilot
from database import DatabaseError
from llm import LLMError
from sql_guard import SQLValidationError


DEFAULT_DATABASE = Path(__file__).parent / "data" / "Chinook_Sqlite.sqlite"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DataPilot V0: natural language to SQL")
    parser.add_argument("question", help="用自然语言提出数据问题")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--show-rows", action="store_true", help="显示原始查询结果")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = DataPilot(args.database).ask(args.question)
    except (ValueError, DatabaseError, LLMError, SQLValidationError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"请求失败：{exc}", file=sys.stderr)
        return 1

    print(f"SQL:\n{result.sql}\n")
    if args.show_rows:
        print("查询结果：")
        print(json.dumps(result.rows, ensure_ascii=False, indent=2, default=str))
        print()
    print(f"回答：\n{result.answer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
