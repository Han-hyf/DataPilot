"""Run DataPilot ablations and calculate execution-based accuracy."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import time
from typing import Any

from agent import DataPilot
from database import Database, create_database
from evaluation.dataset import EvalCase, load_cases
from llm import DeepSeekLLM


@dataclass(frozen=True)
class Profile:
    name: str
    use_schema_rag: bool
    max_retries: int


PROFILES = {
    "baseline": Profile("baseline", use_schema_rag=False, max_retries=0),
    "rag": Profile("rag", use_schema_rag=True, max_retries=0),
    "reflection": Profile("reflection", use_schema_rag=True, max_retries=3),
}


class EvaluationLLM:
    """Use DeepSeek for SQL work but skip the unrelated answer-generation call."""

    def __init__(self) -> None:
        self.delegate = DeepSeekLLM()

    def generate_sql(self, question: str, schema: str, dialect: str) -> str:
        return self.delegate.generate_sql(question, schema, dialect)

    def repair_sql(self, question: str, schema: str, sql: str, error: str, dialect: str) -> str:
        return self.delegate.repair_sql(question, schema, sql, error, dialect)

    @staticmethod
    def analyze(question: str, sql: str, rows: list[dict[str, Any]]) -> str:
        return "evaluation-only"


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return ("number", format(value.normalize(), "f"))
    if isinstance(value, float):
        return ("number", format(Decimal(str(value)).normalize(), "f"))
    if isinstance(value, (datetime, date)):
        return ("datetime", value.isoformat())
    if isinstance(value, bytes):
        return ("bytes", value.hex())
    return (type(value).__name__, value)


def canonical_rows(rows: list[dict[str, Any]], ordered: bool) -> list[tuple[Any, ...]]:
    """Compare values rather than aliases; optionally preserve result order."""
    normalized = [tuple(_normalize(value) for value in row.values()) for row in rows]
    if not ordered:
        normalized.sort(key=lambda row: json.dumps(row, ensure_ascii=False, default=str))
    return normalized


def rows_equal(actual: list[dict[str, Any]], expected: list[dict[str, Any]], ordered: bool) -> bool:
    return canonical_rows(actual, ordered) == canonical_rows(expected, ordered)


def select_cases(cases: list[EvalCase], case_ids: set[str], sample_per_category: int | None) -> list[EvalCase]:
    if case_ids:
        selected = [case for case in cases if case.id in case_ids]
        missing = case_ids - {case.id for case in selected}
        if missing:
            raise ValueError(f"未知 case id：{', '.join(sorted(missing))}")
        return selected
    if sample_per_category is None:
        return cases
    selected: list[EvalCase] = []
    counts: dict[str, int] = {}
    for case in cases:
        count = counts.get(case.category, 0)
        if count < sample_per_category:
            selected.append(case)
            counts[case.category] = count + 1
    return selected


def evaluate_profile(profile: Profile, cases: list[EvalCase], database_target: str | None) -> dict[str, Any]:
    gold_database: Database = create_database(database_target)
    pilot = DataPilot(
        database_target,
        max_retries=profile.max_retries,
        use_mcp=True,
        use_schema_rag=profile.use_schema_rag,
        llm=EvaluationLLM(),
    )
    outcomes: list[dict[str, Any]] = []
    for position, case in enumerate(cases, 1):
        started = time.perf_counter()
        expected_rows = gold_database.execute(case.gold_sql) if case.gold_sql else None
        try:
            result = pilot.ask(case.question)
            error = None
        except Exception as exc:
            result = None
            error = f"{type(exc).__name__}: {exc}"
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

        if case.answerable:
            correct = result is not None and rows_equal(result.rows, expected_rows or [], case.ordered)
        else:
            correct = error is not None
        outcome = {
            "id": case.id,
            "category": case.category,
            "question": case.question,
            "answerable": case.answerable,
            "correct": correct,
            "latency_ms": elapsed_ms,
            "sql": result.sql if result else None,
            "retry_count": result.retry_count if result else 0,
            "error": error,
        }
        outcomes.append(outcome)
        mark = "PASS" if correct else "FAIL"
        print(f"[{profile.name} {position:03d}/{len(cases):03d}] {mark} {case.id} ({elapsed_ms:.0f} ms)")

    return summarize(profile, outcomes)


def summarize(profile: Profile, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    def metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(items)
        correct = sum(bool(item["correct"]) for item in items)
        return {
            "correct": correct,
            "total": total,
            "accuracy": round(correct / total, 4) if total else None,
        }

    categories = sorted({str(item["category"]) for item in outcomes})
    return {
        "profile": asdict(profile),
        "overall": metrics(outcomes),
        "execution_accuracy": metrics([item for item in outcomes if item["answerable"]]),
        "graceful_failure_accuracy": metrics([item for item in outcomes if not item["answerable"]]),
        "by_category": {
            category: metrics([item for item in outcomes if item["category"] == category])
            for category in categories
        },
        "average_latency_ms": round(sum(item["latency_ms"] for item in outcomes) / len(outcomes), 1),
        "total_repairs": sum(int(item["retry_count"]) for item in outcomes),
        "outcomes": outcomes,
    }


def markdown_report(report: dict[str, Any]) -> str:
    def display(metric: dict[str, Any]) -> str:
        accuracy = metric["accuracy"]
        percentage = f"{accuracy:.1%}" if accuracy is not None else "n/a"
        return f"{metric['correct']}/{metric['total']} ({percentage})"

    lines = [
        "# DataPilot Evaluation Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Cases: {report['case_count']}",
        "",
        "| Profile | Overall | Execution Accuracy | Graceful Failure | Avg latency | Repairs |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in report["results"]:
        overall = result["overall"]
        execution = result["execution_accuracy"]
        failure = result["graceful_failure_accuracy"]
        lines.append(
            f"| {result['profile']['name']} | {display(overall)} "
            f"| {display(execution)} "
            f"| {display(failure)} "
            f"| {result['average_latency_ms']:.1f} ms | {result['total_repairs']} |"
        )
    lines.extend(["", "## Category breakdown", ""])
    for result in report["results"]:
        lines.append(f"### {result['profile']['name']}")
        lines.append("")
        for category, metric in result["by_category"].items():
            lines.append(f"- {category}: {display(metric)}")
        lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DataPilot V8 execution-accuracy evaluation")
    parser.add_argument("--database", default=None, help="PostgreSQL URL；默认读取 DATABASE_URL")
    parser.add_argument("--profiles", nargs="+", choices=PROFILES, default=list(PROFILES))
    parser.add_argument("--case-id", action="append", default=[], help="只运行指定 case，可重复")
    parser.add_argument("--sample-per-category", type=int, default=None, help="每类取前 N 题做低成本冒烟测试")
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation/results"))
    parser.add_argument("--list", action="store_true", help="列出题目但不调用模型")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = select_cases(load_cases(), set(args.case_id), args.sample_per_category)
    if args.list:
        for case in cases:
            print(f"{case.id}\t{case.category}\t{case.question}")
        print(f"共 {len(cases)} 题")
        return 0
    if args.sample_per_category is not None and args.sample_per_category < 1:
        raise ValueError("--sample-per-category 必须大于 0。")

    results = [evaluate_profile(PROFILES[name], cases, args.database) for name in args.profiles]
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "case_count": len(cases),
        "results": results,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = args.output_dir / f"evaluation-{stamp}.json"
    markdown_path = args.output_dir / f"evaluation-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
