from __future__ import annotations

from collections import Counter

import sqlglot

from evaluation.dataset import load_cases
from evaluation.run import PROFILES, markdown_report, rows_equal, summarize


def test_dataset_has_planned_100_case_distribution() -> None:
    cases = load_cases()

    assert len(cases) == 100
    assert len({case.id for case in cases}) == 100
    assert Counter(case.category for case in cases) == {
        "simple": 20,
        "aggregate": 20,
        "join": 20,
        "date": 15,
        "business": 15,
        "error": 10,
    }
    assert sum(case.answerable for case in cases) == 90


def test_all_gold_queries_parse_as_single_postgres_query() -> None:
    for case in load_cases():
        if case.gold_sql is None:
            continue
        statements = sqlglot.parse(case.gold_sql, read="postgres")
        assert len(statements) == 1, case.id


def test_result_comparison_ignores_aliases_and_unimportant_order() -> None:
    expected = [{"city": "北京", "count": 2}, {"city": "上海", "count": 1}]
    actual = [{"name": "上海", "total": 1}, {"name": "北京", "total": 2}]

    assert rows_equal(actual, expected, ordered=False)
    assert not rows_equal(actual, expected, ordered=True)


def test_summary_and_markdown_support_empty_robustness_partition() -> None:
    outcomes = [
        {
            "id": "simple-001",
            "category": "simple",
            "answerable": True,
            "correct": True,
            "latency_ms": 10.0,
            "retry_count": 0,
        }
    ]
    summary = summarize(PROFILES["baseline"], outcomes)
    report = {
        "generated_at": "2026-08-21T00:00:00+08:00",
        "case_count": 1,
        "results": [summary],
    }

    assert summary["execution_accuracy"]["accuracy"] == 1.0
    assert summary["graceful_failure_accuracy"]["accuracy"] is None
    assert "0/0 (n/a)" in markdown_report(report)
