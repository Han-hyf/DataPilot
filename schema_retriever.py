"""Lightweight Schema RAG using business semantics and relation-graph expansion."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TableMetadata:
    description: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalResult:
    context: str
    selected_tables: tuple[str, ...]
    used_fallback: bool


TABLE_CATALOG = {
    "users": TableMetadata("用户基础信息、城市、性别和注册时间", ("用户", "客户", "城市", "地区", "注册", "新用户", "老用户")),
    "categories": TableMetadata("商品品类维度", ("品类", "类别", "分类")),
    "products": TableMetadata("商品、售价、成本和所属品类", ("商品", "产品", "售价", "成本", "利润", "毛利")),
    "orders": TableMetadata("订单、用户、状态、金额和下单时间", ("订单", "gmv", "销售额", "成交额", "客单价", "消费", "购买")),
    "order_items": TableMetadata("订单商品明细、数量和成交单价", ("订单项", "明细", "销量", "件数", "数量", "商品销售")),
    "payments": TableMetadata("支付记录、支付方式、金额和支付时间", ("支付", "付款", "支付宝", "微信", "银行卡")),
    "refunds": TableMetadata("退款订单、退款金额、原因和时间", ("退款", "退货", "退款率", "退款金额", "退款原因")),
}

RELATIONSHIPS = {
    "users": {"orders"},
    "orders": {"users", "order_items", "payments", "refunds"},
    "order_items": {"orders", "products"},
    "products": {"order_items", "categories"},
    "categories": {"products"},
    "payments": {"orders"},
    "refunds": {"orders"},
}

BUSINESS_RULES = {
    "gmv": "GMV = SUM(orders.total_amount)，仅统计 PAID、SHIPPED、COMPLETED、REFUNDED 状态。",
    "paid": "有效支付订单使用 PAID、SHIPPED、COMPLETED、REFUNDED；排除 CANCELLED 和 PENDING。",
    "refund": "退款率 = 有退款记录的订单数 / 有效支付订单数；退款金额来自 refunds.refund_amount。",
    "net": "净收入 = GMV - SUM(refunds.refund_amount)。",
    "aov": "客单价 = GMV / 有效支付订单数。",
    "time": "时间字段为 TIMESTAMPTZ；PostgreSQL 按月聚合使用 DATE_TRUNC('month', ...)。",
}

FEW_SHOTS = {
    "gmv": """Question: 每月 GMV
SQL: SELECT DATE_TRUNC('month', created_at) AS month, SUM(total_amount) AS gmv
FROM orders
WHERE status IN ('PAID', 'SHIPPED', 'COMPLETED', 'REFUNDED')
GROUP BY month ORDER BY month""",
    "aov": """Question: 各城市客单价
SQL: SELECT u.city, SUM(o.total_amount) / NULLIF(COUNT(o.id), 0) AS avg_order_value
FROM orders o JOIN users u ON u.id = o.user_id
WHERE o.status IN ('PAID', 'SHIPPED', 'COMPLETED', 'REFUNDED')
GROUP BY u.city ORDER BY avg_order_value DESC""",
    "product_sales": """Question: 销售额最高的商品品类
SQL: SELECT c.name, SUM(oi.quantity * oi.unit_price) AS sales
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
JOIN products p ON p.id = oi.product_id
JOIN categories c ON c.id = p.category_id
WHERE o.status IN ('PAID', 'SHIPPED', 'COMPLETED', 'REFUNDED')
GROUP BY c.name ORDER BY sales DESC""",
}


class SchemaRetriever:
    def __init__(self, top_k: int = 3) -> None:
        if top_k < 1:
            raise ValueError("top_k 必须大于 0。")
        self.top_k = top_k

    @staticmethod
    def _table_blocks(schema: str) -> dict[str, str]:
        blocks: dict[str, str] = {}
        for block in re.split(r"\n\s*\n", schema.strip()):
            match = re.match(
                r'(?:TABLE|CREATE\s+TABLE)\s+["`\[]?([A-Za-z_][\w]*)',
                block,
                flags=re.IGNORECASE,
            )
            if match:
                blocks[match.group(1).lower()] = block.strip()
        return blocks

    @staticmethod
    def _score(question: str, table: str, metadata: TableMetadata) -> int:
        text = question.lower()
        score = 0
        if table in text:
            score += 8
        for keyword in metadata.keywords:
            if keyword.lower() in text:
                score += max(3, len(keyword))
        for token in re.findall(r"[a-z0-9_]+", metadata.description.lower()):
            if token in text:
                score += 1
        return score

    @staticmethod
    def _shortest_path(start: str, end: str) -> list[str]:
        queue = deque([(start, [start])])
        visited = {start}
        while queue:
            current, path = queue.popleft()
            if current == end:
                return path
            for neighbor in RELATIONSHIPS.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        return []

    def _connect_tables(self, selected: list[str]) -> set[str]:
        connected = set(selected)
        for index, start in enumerate(selected):
            for end in selected[index + 1 :]:
                connected.update(self._shortest_path(start, end))
        return connected

    @staticmethod
    def _relevant_rules(question: str) -> list[str]:
        text = question.lower()
        rules = []
        if any(key in text for key in ("gmv", "销售额", "成交额")):
            rules.extend([BUSINESS_RULES["gmv"], BUSINESS_RULES["paid"]])
        if any(key in text for key in ("退款", "退货")):
            rules.extend([BUSINESS_RULES["refund"], BUSINESS_RULES["paid"]])
        if any(key in text for key in ("净收入", "净销售")):
            rules.extend([BUSINESS_RULES["net"], BUSINESS_RULES["gmv"]])
        if "客单价" in text:
            rules.extend([BUSINESS_RULES["aov"], BUSINESS_RULES["paid"]])
        if any(key in text for key in ("月", "季度", "年", "最近", "近")):
            rules.append(BUSINESS_RULES["time"])
        return list(dict.fromkeys(rules))

    @staticmethod
    def _relevant_examples(question: str) -> list[str]:
        text = question.lower()
        examples = []
        if any(key in text for key in ("gmv", "销售额", "成交额")):
            examples.append(FEW_SHOTS["gmv"])
        if "客单价" in text:
            examples.append(FEW_SHOTS["aov"])
        if any(key in text for key in ("商品", "产品", "品类")) and any(
            key in text for key in ("销售额", "销量", "成交额")
        ):
            examples.append(FEW_SHOTS["product_sales"])
        return examples[:2]

    def retrieve(self, question: str, schema: str, dialect: str) -> RetrievalResult:
        blocks = self._table_blocks(schema)
        if dialect != "postgres" or not set(TABLE_CATALOG).issubset(blocks):
            return RetrievalResult(schema, tuple(sorted(blocks)), True)

        ranked = sorted(
            (
                (self._score(question, table, metadata), table)
                for table, metadata in TABLE_CATALOG.items()
            ),
            reverse=True,
        )
        selected = [table for score, table in ranked[: self.top_k] if score > 0]
        if not selected:
            return RetrievalResult(schema, tuple(sorted(blocks)), True)

        connected = self._connect_tables(selected)
        ordered_tables = tuple(table for table in blocks if table in connected)
        context_parts = [
            f"DATABASE DIALECT: {dialect}",
            "RETRIEVED SCHEMA:\n" + "\n\n".join(blocks[table] for table in ordered_tables),
        ]
        descriptions = [
            f"- {table}: {TABLE_CATALOG[table].description}" for table in ordered_tables
        ]
        context_parts.append("BUSINESS SEMANTICS:\n" + "\n".join(descriptions))
        rules = self._relevant_rules(question)
        if rules:
            context_parts.append("RELEVANT RULES:\n- " + "\n- ".join(rules))
        examples = self._relevant_examples(question)
        if examples:
            context_parts.append("RELEVANT SQL EXAMPLES:\n" + "\n\n".join(examples))
        return RetrievalResult("\n\n".join(context_parts), ordered_tables, False)
