# DataPilot

DataPilot 是一个逐步演进的智能数据分析 Agent。当前 V1 使用 LangGraph 显式编排最小可用链路：

```text
自然语言问题 → 获取 Schema → DeepSeek 生成 SQL → 执行真实查询 → 生成中文答案
```

```text
START → get_schema → generate_sql → execute_sql → analyze_result → END
```

当前版本刻意不引入 Schema RAG、MCP 或 Web API。V1 只负责把 V0 重构为可观察、可扩展的状态图；SQL 校验分支和错误修复循环将在后续版本加入。

## V1 快速开始

要求 Python 3.11+。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 中填入自己的 `DEEPSEEK_API_KEY`，然后下载官方 Chinook 示例数据库：

```powershell
python scripts/download_chinook.py
```

执行查询：

```powershell
python main.py "销售额最高的5位客户是谁？" --show-rows
```

运行测试：

```powershell
python -m pytest
```

## V1 文件

- `main.py`：命令行入口
- `agent.py`：LangGraph State、节点、边和 Text2SQL 工作流
- `llm.py`：DeepSeek API 调用
- `database.py`：只读 SQLite Schema 获取与查询执行
- `scripts/download_chinook.py`：下载官方 Chinook 数据库
- `tests/`：不调用外部 API 的单元测试

## 安全边界

数据库以 SQLite 只读模式打开，并启用 `query_only`。V0 还会拒绝多语句和无结果语句。更完整的 SQL AST 校验、超时和风险策略将在 SQL Guard 阶段实现。
