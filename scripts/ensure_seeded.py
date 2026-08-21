"""Idempotently seed the ecommerce database for Docker Compose."""

from __future__ import annotations

import argparse
import os

import psycopg

from scripts.seed_ecommerce import seed


def _positive_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} 必须大于 0。")
    return value


def main() -> int:
    database_url = os.getenv("DATABASE_ADMIN_URL")
    if not database_url:
        raise RuntimeError("缺少 DATABASE_ADMIN_URL。")
    args = argparse.Namespace(
        users=_positive_env("SEED_USERS", 10_000),
        products=_positive_env("SEED_PRODUCTS", 500),
        orders=_positive_env("SEED_ORDERS", 50_000),
        seed=int(os.getenv("SEED_RANDOM_SEED", "20260819")),
        reset=False,
    )
    with psycopg.connect(database_url) as connection:
        count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count:
            print(f"数据库已有 {count} 个用户，跳过种子数据生成。")
            return 0
        seed(connection, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
