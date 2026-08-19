# DataPilot

DataPilot 是一个逐步演进的智能数据分析 Agent。当前 V3 支持 SQL Reflection 自动修复：

```text
自然语言问题 → 获取 Schema → DeepSeek 生成 SQL → 执行真实查询 → 生成中文答案
```

```text
START → get_schema → generate_sql → validate_sql
                                      ├─ 拒绝 → reject → END
                                      └─ 通过 → execute_sql
                                                   ├─ 成功 → analyze_result → END
                                                   ├─ 失败且可重试 → repair_sql
                                                   │                  ↓
                                                   │             validate_sql
                                                   └─ 达到上限 → fail → END
```

当前版本刻意不引入 Schema RAG、MCP 或 Web API。V3 会把执行失败的 SQL、SQLite 错误、Schema 和原问题交给 DeepSeek 修复；每条修复 SQL 都必须重新通过 SQL Guard，默认最多修复 3 次。

## V3 快速开始

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

## V3 文件

- `main.py`：命令行入口
- `agent.py`：LangGraph State、节点、边和 Text2SQL 工作流
- `llm.py`：DeepSeek API 调用
- `database.py`：只读 SQLite Schema 获取与查询执行
- `sql_guard.py`：SQL AST 校验与结果行数限制
- `scripts/download_chinook.py`：下载官方 Chinook 数据库
- `tests/`：不调用外部 API 的单元测试

## 安全边界

V2 采用多层防护：

- SQLGlot AST 仅放行单条 `SELECT` / `WITH` 查询
- 拒绝 DDL、DML、PRAGMA、多语句和 `load_extension`
- 自动添加 `LIMIT 100`，并将更大的 LIMIT 收紧为 100
- 查询超过 3 秒会被 SQLite progress handler 中断
- 数据库以只读 URI 打开，并启用 SQLite `query_only`

SQL Guard 不能替代生产环境的最小权限数据库账号；迁移 PostgreSQL 时仍需为 Agent 配置只读用户。

## SQL Reflection

- 只捕获已经通过 SQL Guard 后发生的数据库执行错误
- 修复提示包含用户问题、Schema、失败 SQL 和真实数据库错误
- 修复 SQL 必须再次经过 AST 安全校验
- 默认最多修复 3 次，达到上限后返回明确错误
- 安全校验失败不会进入 Reflection，避免模型尝试绕过 Guard
