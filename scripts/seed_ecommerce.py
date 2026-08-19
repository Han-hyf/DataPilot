"""Generate deterministic ecommerce data for the PostgreSQL V4 database."""

from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg
from dotenv import load_dotenv
from faker import Faker


CATEGORY_NAMES = [
    "手机数码", "电脑办公", "家用电器", "服装鞋包", "食品饮料", "美妆个护",
    "家居家装", "运动户外", "母婴用品", "图书音像", "汽车用品", "宠物生活",
]
CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京"]
REFUND_REASONS = ["商品质量问题", "尺寸不合适", "与描述不符", "物流损坏", "重复购买"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 DataPilot 电商测试数据")
    parser.add_argument("--users", type=int, default=10_000)
    parser.add_argument("--products", type=int, default=500)
    parser.add_argument("--orders", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=20260819)
    parser.add_argument("--reset", action="store_true", help="清空已有业务数据")
    return parser.parse_args()


def money(value: float) -> Decimal:
    return Decimal(str(round(value, 2)))


def seed(connection: psycopg.Connection, args: argparse.Namespace) -> None:
    rng = random.Random(args.seed)
    fake = Faker("zh_CN")
    Faker.seed(args.seed)
    now = datetime.now(timezone.utc)

    with connection.cursor() as cursor:
        if args.reset:
            cursor.execute(
                "TRUNCATE refunds, payments, order_items, orders, products, "
                "categories, users RESTART IDENTITY CASCADE"
            )
        elif cursor.execute("SELECT EXISTS (SELECT 1 FROM users)").fetchone()[0]:
            raise RuntimeError("数据库已有数据；如需重建，请添加 --reset。")

        cursor.executemany(
            "INSERT INTO categories(name) VALUES (%s)",
            [(name,) for name in CATEGORY_NAMES],
        )

        users = []
        for _ in range(args.users):
            users.append(
                (
                    fake.name(),
                    rng.choices(["MALE", "FEMALE", "UNKNOWN"], [49, 49, 2])[0],
                    rng.choice(CITIES),
                    now - timedelta(days=rng.randint(30, 1_095)),
                )
            )
        cursor.executemany(
            "INSERT INTO users(name, gender, city, register_time) VALUES (%s, %s, %s, %s)",
            users,
        )

        product_prices: dict[int, Decimal] = {}
        products = []
        for product_id in range(1, args.products + 1):
            price = money(rng.uniform(15, 5000))
            product_prices[product_id] = price
            products.append(
                (
                    f"{fake.word()}-{product_id:04d}",
                    rng.randint(1, len(CATEGORY_NAMES)),
                    price,
                    money(float(price) * rng.uniform(0.45, 0.82)),
                    now - timedelta(days=rng.randint(30, 1_095)),
                )
            )
        cursor.executemany(
            "INSERT INTO products(name, category_id, price, cost, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            products,
        )

        orders = []
        order_items = []
        payments = []
        refunds = []
        statuses = ["PAID", "SHIPPED", "COMPLETED", "CANCELLED", "REFUNDED"]
        weights = [12, 18, 55, 10, 5]
        item_id = payment_id = refund_id = 1

        for order_id in range(1, args.orders + 1):
            created_at = now - timedelta(
                days=rng.randint(0, 729), seconds=rng.randint(0, 86_399)
            )
            status = rng.choices(statuses, weights)[0]
            selected_products = rng.sample(
                range(1, args.products + 1),
                k=min(rng.randint(1, 5), args.products),
            )
            total = Decimal("0")
            for product_id in selected_products:
                quantity = rng.randint(1, 3)
                unit_price = product_prices[product_id]
                total += unit_price * quantity
                order_items.append((item_id, order_id, product_id, quantity, unit_price))
                item_id += 1

            total = total.quantize(Decimal("0.01"))
            orders.append((order_id, rng.randint(1, args.users), status, total, created_at))
            if status != "CANCELLED":
                payments.append(
                    (
                        payment_id,
                        order_id,
                        rng.choice(["ALIPAY", "WECHAT", "CARD"]),
                        total,
                        created_at + timedelta(minutes=rng.randint(1, 120)),
                    )
                )
                payment_id += 1
            if status == "REFUNDED":
                refunds.append(
                    (
                        refund_id,
                        order_id,
                        money(float(total) * rng.uniform(0.25, 1.0)),
                        rng.choice(REFUND_REASONS),
                        created_at + timedelta(days=rng.randint(1, 14)),
                    )
                )
                refund_id += 1

        cursor.executemany(
            "INSERT INTO orders(id, user_id, status, total_amount, created_at) "
            "VALUES (%s, %s, %s, %s, %s)", orders,
        )
        cursor.executemany(
            "INSERT INTO order_items(id, order_id, product_id, quantity, unit_price) "
            "VALUES (%s, %s, %s, %s, %s)", order_items,
        )
        cursor.executemany(
            "INSERT INTO payments(id, order_id, method, amount, paid_at) "
            "VALUES (%s, %s, %s, %s, %s)", payments,
        )
        cursor.executemany(
            "INSERT INTO refunds(id, order_id, refund_amount, reason, created_at) "
            "VALUES (%s, %s, %s, %s, %s)", refunds,
        )
        for table in ("orders", "order_items", "payments", "refunds"):
            cursor.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
            )
    connection.commit()

    print(
        f"生成完成：{args.users} 用户，{args.products} 商品，"
        f"{args.orders} 订单，{len(order_items)} 订单项，{len(refunds)} 退款"
    )


def main() -> None:
    load_dotenv()
    database_url = os.getenv("DATABASE_ADMIN_URL")
    if not database_url:
        raise RuntimeError("缺少 DATABASE_ADMIN_URL，请在 .env 中配置。")
    args = parse_args()
    if min(args.users, args.products, args.orders) < 1:
        raise ValueError("users、products 和 orders 必须大于 0。")
    with psycopg.connect(database_url) as connection:
        seed(connection, args)


if __name__ == "__main__":
    main()
