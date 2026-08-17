"""DeepSeek client used by the V0 pipeline."""

from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


class LLMError(RuntimeError):
    """Raised when the model response cannot be used."""


class DeepSeekLLM:
    def __init__(self) -> None:
        load_dotenv()
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise LLMError("缺少 DEEPSEEK_API_KEY，请在 .env 中配置。")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self.client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )

    def _json_completion(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=1200,
        )
        content = response.choices[0].message.content
        if not content:
            raise LLMError("模型返回了空响应。")
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError("模型没有返回有效 JSON。") from exc
        if not isinstance(result, dict):
            raise LLMError("模型响应必须是 JSON 对象。")
        return result

    def generate_sql(self, question: str, schema: str) -> str:
        result = self._json_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 SQLite 数据分析专家。根据给定 schema 和用户问题生成一条只读查询。"
                        "只能使用 schema 中存在的表和字段；禁止修改数据；结果默认不超过 100 行。"
                        '必须仅输出 JSON，例如：{"sql":"SELECT ... LIMIT 100"}。'
                    ),
                },
                {
                    "role": "user",
                    "content": f"数据库 schema：\n{schema}\n\n用户问题：{question}",
                },
            ]
        )
        sql = result.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            raise LLMError("模型响应中缺少 sql 字段。")
        return sql.strip()

    def analyze(self, question: str, sql: str, rows: list[dict[str, Any]]) -> str:
        result = self._json_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是数据分析助手。只能根据提供的真实查询结果回答，不得编造。"
                        "回答简洁、明确，并保留关键数值。"
                        '必须仅输出 JSON，例如：{"answer":"分析结论"}。'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"用户问题：{question}\n执行的 SQL：{sql}\n"
                        f"查询结果：{json.dumps(rows, ensure_ascii=False, default=str)}"
                    ),
                },
            ]
        )
        answer = result.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise LLMError("模型响应中缺少 answer 字段。")
        return answer.strip()
