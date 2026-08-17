# DataPilot

DataPilot 是一个逐步演进的智能数据分析 Agent。V0 实现最小可用链路：

```text
自然语言问题 → DeepSeek 生成 SQLite 查询 → 执行真实查询 → 生成中文答案
```

当前版本刻意不引入 LangGraph、Schema RAG、MCP 或 Web API，以便先验证 Text2SQL 核心能力。

## V0 快速开始

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

## V0 文件

- `main.py`：命令行入口
- `agent.py`：Text2SQL 管道
- `llm.py`：DeepSeek API 调用
- `database.py`：只读 SQLite Schema 获取与查询执行
- `scripts/download_chinook.py`：下载官方 Chinook 数据库
- `tests/`：不调用外部 API 的单元测试

## 安全边界

数据库以 SQLite 只读模式打开，并启用 `query_only`。V0 还会拒绝多语句和无结果语句。更完整的 SQL AST 校验、超时和风险策略将在 SQL Guard 阶段实现。
