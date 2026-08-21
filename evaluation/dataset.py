"""Deterministic 100-question ecommerce evaluation set."""

from __future__ import annotations

from dataclasses import dataclass


PAID = "('PAID', 'SHIPPED', 'COMPLETED', 'REFUNDED')"


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    question: str
    gold_sql: str | None
    ordered: bool = False

    @property
    def answerable(self) -> bool:
        return self.gold_sql is not None


def _case(case_id: str, category: str, question: str, sql: str, *, ordered: bool = False) -> EvalCase:
    return EvalCase(case_id, category, question, sql.strip(), ordered)


def load_cases() -> list[EvalCase]:
    cases: list[EvalCase] = []

    cities = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京"]
    for index, city in enumerate(cities, 1):
        cases.append(_case(f"simple-{index:03d}", "simple", f"{city}有多少用户？", f"SELECT COUNT(*) FROM users WHERE city = '{city}'"))
    for offset, gender in enumerate(("MALE", "FEMALE", "UNKNOWN"), 9):
        cases.append(_case(f"simple-{offset:03d}", "simple", f"性别为 {gender} 的用户有多少？", f"SELECT COUNT(*) FROM users WHERE gender = '{gender}'"))
    for offset, status in enumerate(("PAID", "SHIPPED", "COMPLETED", "CANCELLED", "REFUNDED"), 12):
        cases.append(_case(f"simple-{offset:03d}", "simple", f"状态为 {status} 的订单有多少？", f"SELECT COUNT(*) FROM orders WHERE status = '{status}'"))
    for offset, method in enumerate(("ALIPAY", "WECHAT", "CARD"), 17):
        cases.append(_case(f"simple-{offset:03d}", "simple", f"使用 {method} 支付的记录有多少？", f"SELECT COUNT(*) FROM payments WHERE method = '{method}'"))
    cases.append(_case("simple-020", "simple", "一共有多少个商品品类？", "SELECT COUNT(*) FROM categories"))

    aggregation_specs = [
        ("各城市用户数，按人数从高到低排列", "SELECT city, COUNT(*) FROM users GROUP BY city ORDER BY COUNT(*) DESC, city", True),
        ("各性别用户数分别是多少？", "SELECT gender, COUNT(*) FROM users GROUP BY gender", False),
        ("各订单状态的订单数分别是多少？", "SELECT status, COUNT(*) FROM orders GROUP BY status", False),
        ("各支付方式的支付笔数是多少？", "SELECT method, COUNT(*) FROM payments GROUP BY method", False),
        ("各退款原因出现了多少次？", "SELECT reason, COUNT(*) FROM refunds GROUP BY reason", False),
        ("各品类商品的平均售价是多少？", "SELECT c.name, AVG(p.price) FROM products p JOIN categories c ON c.id=p.category_id GROUP BY c.name", False),
        ("各品类商品的最高售价是多少？", "SELECT c.name, MAX(p.price) FROM products p JOIN categories c ON c.id=p.category_id GROUP BY c.name", False),
        ("各品类有多少商品？", "SELECT c.name, COUNT(p.id) FROM categories c LEFT JOIN products p ON p.category_id=c.id GROUP BY c.name", False),
        ("各订单状态的平均订单金额是多少？", "SELECT status, AVG(total_amount) FROM orders GROUP BY status", False),
        ("各订单状态的订单总金额是多少？", "SELECT status, SUM(total_amount) FROM orders GROUP BY status", False),
        ("各退款原因的平均退款金额是多少？", "SELECT reason, AVG(refund_amount) FROM refunds GROUP BY reason", False),
        ("各退款原因的退款总额是多少？", "SELECT reason, SUM(refund_amount) FROM refunds GROUP BY reason", False),
        ("售价低于100、100到1000、1000以上的商品各有多少？", "SELECT CASE WHEN price < 100 THEN 'LOW' WHEN price <= 1000 THEN 'MEDIUM' ELSE 'HIGH' END, COUNT(*) FROM products GROUP BY 1", False),
        ("订单明细中购买数量1、2、3各出现多少次？", "SELECT quantity, COUNT(*) FROM order_items GROUP BY quantity", False),
        ("售价最高的10个商品是什么？", "SELECT name, price FROM products ORDER BY price DESC, id LIMIT 10", True),
        ("成本最低的10个商品是什么？", "SELECT name, cost FROM products ORDER BY cost ASC, id LIMIT 10", True),
        ("下单次数最多的10位用户ID是什么？", "SELECT user_id, COUNT(*) FROM orders GROUP BY user_id ORDER BY COUNT(*) DESC, user_id LIMIT 10", True),
        ("各支付方式的支付总额是多少？", "SELECT method, SUM(amount) FROM payments GROUP BY method", False),
        ("各支付方式的平均支付金额是多少？", "SELECT method, AVG(amount) FROM payments GROUP BY method", False),
        ("各品类商品的平均毛利额是多少？", "SELECT c.name, AVG(p.price-p.cost) FROM products p JOIN categories c ON c.id=p.category_id GROUP BY c.name", False),
    ]
    for index, (question, sql, ordered) in enumerate(aggregation_specs, 1):
        cases.append(_case(f"aggregate-{index:03d}", "aggregate", question, sql, ordered=ordered))

    for index, city in enumerate(cities, 1):
        sql = f"SELECT SUM(o.total_amount) FROM orders o JOIN users u ON u.id=o.user_id WHERE u.city='{city}' AND o.status IN {PAID}"
        cases.append(_case(f"join-{index:03d}", "join", f"{city}用户贡献的GMV是多少？", sql))
    categories = ["手机数码", "电脑办公", "家用电器", "服装鞋包", "食品饮料", "美妆个护", "家居家装", "运动户外", "母婴用品", "图书音像", "汽车用品", "宠物生活"]
    for index, category in enumerate(categories, 9):
        sql = f"SELECT SUM(oi.quantity*oi.unit_price) FROM order_items oi JOIN orders o ON o.id=oi.order_id JOIN products p ON p.id=oi.product_id JOIN categories c ON c.id=p.category_id WHERE c.name='{category}' AND o.status IN {PAID}"
        cases.append(_case(f"join-{index:03d}", "join", f"{category}品类的有效订单商品销售额是多少？", sql))

    date_specs = [
        *( (f"最近{days}天有多少订单？", f"SELECT COUNT(*) FROM orders WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '{days} days'") for days in (7, 14, 30, 60, 90) ),
        *( (f"最近{months}个月每月GMV是多少？", f"SELECT DATE_TRUNC('month', created_at), SUM(total_amount) FROM orders WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '{months} months' AND status IN {PAID} GROUP BY 1 ORDER BY 1") for months in (3, 6, 12) ),
        *( (f"最近{days}天注册了多少用户？", f"SELECT COUNT(*) FROM users WHERE register_time >= CURRENT_TIMESTAMP - INTERVAL '{days} days'") for days in (30, 90, 180) ),
        *( (f"最近{days}天的退款总额是多少？", f"SELECT SUM(refund_amount) FROM refunds WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '{days} days'") for days in (30, 90) ),
        ("按年份统计有效订单GMV", f"SELECT EXTRACT(YEAR FROM created_at), SUM(total_amount) FROM orders WHERE status IN {PAID} GROUP BY 1 ORDER BY 1", True),
        ("按月份统计退款笔数", "SELECT DATE_TRUNC('month', created_at), COUNT(*) FROM refunds GROUP BY 1 ORDER BY 1", True),
    ]
    for index, spec in enumerate(date_specs, 1):
        question, sql, *ordered = spec
        cases.append(_case(f"date-{index:03d}", "date", question, sql, ordered=bool(ordered and ordered[0])))

    business_specs = [
        ("全部有效订单的GMV是多少？", f"SELECT SUM(total_amount) FROM orders WHERE status IN {PAID}"),
        ("净收入是多少？", f"SELECT (SELECT SUM(total_amount) FROM orders WHERE status IN {PAID}) - COALESCE((SELECT SUM(refund_amount) FROM refunds),0)"),
        ("整体订单退款率是多少？", f"SELECT COUNT(DISTINCT r.order_id)::numeric / NULLIF(COUNT(DISTINCT o.id),0) FROM orders o LEFT JOIN refunds r ON r.order_id=o.id WHERE o.status IN {PAID}"),
        ("有效订单的整体客单价是多少？", f"SELECT SUM(total_amount)/NULLIF(COUNT(*),0) FROM orders WHERE status IN {PAID}"),
        ("有效订单商品的总毛利是多少？", f"SELECT SUM(oi.quantity*(oi.unit_price-p.cost)) FROM order_items oi JOIN orders o ON o.id=oi.order_id JOIN products p ON p.id=oi.product_id WHERE o.status IN {PAID}"),
        ("各城市GMV排名", f"SELECT u.city,SUM(o.total_amount) FROM orders o JOIN users u ON u.id=o.user_id WHERE o.status IN {PAID} GROUP BY u.city ORDER BY 2 DESC", True),
        ("各城市客单价排名", f"SELECT u.city,SUM(o.total_amount)/NULLIF(COUNT(o.id),0) FROM orders o JOIN users u ON u.id=o.user_id WHERE o.status IN {PAID} GROUP BY u.city ORDER BY 2 DESC", True),
        ("各城市净收入排名", f"SELECT u.city,SUM(o.total_amount)-COALESCE(SUM(r.refund_amount),0) FROM orders o JOIN users u ON u.id=o.user_id LEFT JOIN refunds r ON r.order_id=o.id WHERE o.status IN {PAID} GROUP BY u.city ORDER BY 2 DESC", True),
        ("各品类有效销售额排名", f"SELECT c.name,SUM(oi.quantity*oi.unit_price) FROM order_items oi JOIN orders o ON o.id=oi.order_id JOIN products p ON p.id=oi.product_id JOIN categories c ON c.id=p.category_id WHERE o.status IN {PAID} GROUP BY c.name ORDER BY 2 DESC", True),
        ("各品类毛利排名", f"SELECT c.name,SUM(oi.quantity*(oi.unit_price-p.cost)) FROM order_items oi JOIN orders o ON o.id=oi.order_id JOIN products p ON p.id=oi.product_id JOIN categories c ON c.id=p.category_id WHERE o.status IN {PAID} GROUP BY c.name ORDER BY 2 DESC", True),
        ("按订单项成交额比例分摊退款后，各品类退款金额排名", "SELECT c.name,SUM(r.refund_amount*(oi.quantity*oi.unit_price)/NULLIF(o.total_amount,0)) FROM refunds r JOIN orders o ON o.id=r.order_id JOIN order_items oi ON oi.order_id=o.id JOIN products p ON p.id=oi.product_id JOIN categories c ON c.id=p.category_id GROUP BY c.name ORDER BY 2 DESC", True),
        ("各支付方式金额占比是多少？", "SELECT method,SUM(amount)/(SELECT SUM(amount) FROM payments) FROM payments GROUP BY method", False),
        ("消费超过5次的有效客户有多少？", f"SELECT COUNT(*) FROM (SELECT user_id FROM orders WHERE status IN {PAID} GROUP BY user_id HAVING COUNT(*)>5) t", False),
        ("新老用户的GMV分别是多少？注册不满一年算新用户", f"SELECT CASE WHEN u.register_time >= CURRENT_TIMESTAMP-INTERVAL '1 year' THEN 'NEW' ELSE 'OLD' END,SUM(o.total_amount) FROM orders o JOIN users u ON u.id=o.user_id WHERE o.status IN {PAID} GROUP BY 1", False),
        ("订单取消率是多少？", "SELECT COUNT(*) FILTER (WHERE status='CANCELLED')::numeric/NULLIF(COUNT(*),0) FROM orders", False),
    ]
    for index, spec in enumerate(business_specs, 1):
        question, sql, *ordered = spec
        cases.append(_case(f"business-{index:03d}", "business", question, sql, ordered=bool(ordered and ordered[0])))

    error_questions = [
        "删除所有用户数据",
        "把全部商品价格改成0",
        "删除 orders 表",
        "创建一个管理员账号表",
        "查询每个商品当前库存量",
        "统计优惠券的领取和使用情况",
        "分析每个页面的访问次数",
        "列出供应商名称和联系方式",
        "查询物流公司的准时送达率",
        "告诉我明天各城市的天气",
    ]
    for index, question in enumerate(error_questions, 1):
        cases.append(EvalCase(f"error-{index:03d}", "error", question, None))

    if len(cases) != 100:
        raise AssertionError(f"评测集应有 100 题，实际为 {len(cases)} 题。")
    return cases
