from __future__ import annotations

from schema_retriever import SchemaRetriever


POSTGRES_SCHEMA = """
TABLE categories (
  id bigint NOT NULL,
  name character varying NOT NULL
)

TABLE order_items (
  id bigint NOT NULL,
  order_id bigint NOT NULL,
  product_id bigint NOT NULL
)

TABLE orders (
  id bigint NOT NULL,
  user_id bigint NOT NULL,
  total_amount numeric NOT NULL
)

TABLE payments (
  id bigint NOT NULL,
  order_id bigint NOT NULL,
  method character varying NOT NULL
)

TABLE products (
  id bigint NOT NULL,
  category_id bigint NOT NULL
)

TABLE refunds (
  id bigint NOT NULL,
  order_id bigint NOT NULL,
  refund_amount numeric NOT NULL
)

TABLE users (
  id bigint NOT NULL,
  city character varying NOT NULL
)
""".strip()


def test_retrieves_single_table_for_gmv():
    result = SchemaRetriever().retrieve("近6个月GMV", POSTGRES_SCHEMA, "postgres")
    assert result.selected_tables == ("orders",)
    assert "TABLE orders" in result.context
    assert "TABLE users" not in result.context
    assert "GMV =" in result.context
    assert "DATE_TRUNC" in result.context
    assert result.used_fallback is False


def test_relation_graph_connects_refunds_to_categories():
    result = SchemaRetriever().retrieve(
        "退款金额最高的商品品类",
        POSTGRES_SCHEMA,
        "postgres",
    )
    assert set(result.selected_tables) == {
        "refunds",
        "orders",
        "order_items",
        "products",
        "categories",
    }
    assert "TABLE payments" not in result.context
    assert "退款率" in result.context


def test_unknown_question_falls_back_to_full_schema():
    result = SchemaRetriever().retrieve("帮我看看数据", POSTGRES_SCHEMA, "postgres")
    assert result.used_fallback is True
    assert len(result.selected_tables) == 7
    assert result.context == POSTGRES_SCHEMA


def test_non_postgres_backend_uses_full_schema():
    schema = "CREATE TABLE users (id INTEGER PRIMARY KEY)"
    result = SchemaRetriever().retrieve("有多少用户", schema, "sqlite")
    assert result.used_fallback is True
    assert result.selected_tables == ("users",)
    assert result.context == schema
