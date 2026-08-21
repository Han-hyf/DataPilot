# DataPilot

DataPilot 是一个逐步演进的智能数据分析 Agent。当前 V7 已将数据库能力封装为标准 MCP 工具，Agent 默认通过官方 MCP Client 调用只读 MCP Server；Schema RAG、SQL Guard 与 Reflection 工作流保持不变。

```text
自然语言问题 → LangGraph → MCP Client → 只读 MCP Server → PostgreSQL
```

```text
START → get_schema → retrieve_schema → generate_sql → validate_sql
                                      ├─ 拒绝 → reject → END
                                      └─ 通过 → execute_sql
                                                   ├─ 成功 → analyze_result → END
                                                   ├─ 失败且可重试 → repair_sql
                                                   │                  ↓
                                                   │             validate_sql
                                                   └─ 达到上限 → fail → END
```

V7 会根据数据库后端自动选择 PostgreSQL 或 SQLite 方言。MCP Server 在工具边界再次执行 SQL Guard，因此外部 Client 也不能绕过只读策略。PostgreSQL 查询仍优先使用相关 Schema，执行失败时使用同一份检索上下文进行 Reflection。

## V7 快速开始

要求 Python 3.11+。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 中填入自己的 `DEEPSEEK_API_KEY` 和本地 PostgreSQL 配置，然后启动数据库：

```powershell
docker compose up -d postgres
python scripts/seed_ecommerce.py
```

默认会生成 10,000 个用户、500 个商品、50,000 个订单及约 15 万条订单项。重新生成数据时添加 `--reset`。如需先做快速验证，可以使用：

```powershell
python scripts/seed_ecommerce.py --users 100 --products 30 --orders 500 --reset
```

执行查询：

```powershell
python main.py "近6个月每个月的GMV是多少？" --show-rows
```

启动 API：

```powershell
python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

单独启动 stdio MCP Server（供 MCP Inspector 等客户端连接）：

```powershell
python mcp_server.py
```

默认 `DATAPILOT_USE_MCP=true`，Agent 使用官方 SDK 的进程内 transport，避免为每次查询额外启动子进程。设为 `false` 可回退到直接 Python 数据库适配器，便于故障排查。

启动后可访问交互式 API 文档：`http://127.0.0.1:8000/docs`。

同步查询：

```powershell
$body = @{question="各城市的用户数量排名前5是什么？"} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/query `
  -ContentType "application/json" -Body $body
```

## API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/health` | 检查 API 和数据库连接 |
| GET | `/api/schema` | 获取当前数据库方言和 Schema |
| POST | `/api/query` | 同步执行查询并返回命中的 Schema 表 |
| POST | `/api/chat` | 同步查询别名 |
| POST | `/api/chat/stream` | 通过 SSE 推送节点进度与结果 |

SSE 事件类型包括 `progress`、`result`、`error` 和 `done`。进度事件对应 `get_schema`、`retrieve_schema`、`generate_sql`、`validate_sql`、`execute_sql`、`repair_sql` 和 `analyze_result` 节点。

运行测试：

```powershell
python -m pytest
```

PostgreSQL 容器已启动且完整数据已生成时，可额外运行集成测试：

```powershell
$env:RUN_POSTGRES_TESTS="1"
python -m pytest tests/test_postgres_integration.py
```

## V6 Schema RAG

当前数据库只有 7 张表，因此 V6 没有强行引入向量数据库，而是采用可解释的混合检索：

1. 使用中文业务关键词与表语义描述召回候选表。
2. 在外键关系图中计算候选表之间的最短路径。
3. 补齐生成 JOIN 所需的中间表。
4. 根据问题选择 GMV、退款率、净收入、客单价等业务规则。
5. 按需加入最多两个 Few-shot SQL 示例。
6. 没有可靠命中时回退完整 Schema，避免召回失败导致 SQL 无法生成。

例如“退款金额最高的商品品类”会召回：

```text
refunds → orders → order_items → products → categories
```

当业务库扩展到约 30 张表以上时，再将第一步替换为 Qdrant dense/sparse hybrid retrieval；关系图补全、业务规则和回退机制可以继续复用。

## V7 MCP 工具

| 工具 | 作用 | 防护 |
| --- | --- | --- |
| `get_schema` | 返回方言、完整 Schema 和表清单 | 只读元数据 |
| `execute_readonly_sql` | 执行单条查询并返回结构化行数据 | 服务端 SQL Guard、LIMIT 100、数据库只读权限 |
| `get_table_statistics` | 返回白名单表的精确行数 | Schema 表名白名单、标识符引用 |

`create_mcp_server(database)` 支持依赖注入，测试使用临时 SQLite 和官方进程内 Client 完成真实 MCP 调用；生产环境使用 `.env` 中的只读 PostgreSQL URL。

## V7 数据模型

```text
users → orders → order_items → products → categories
           ├── payments
           └── refunds
```

业务口径：GMV 默认统计 `PAID`、`SHIPPED`、`COMPLETED`、`REFUNDED` 状态的订单；退款金额单独从 `refunds` 表汇总。

## V7 文件

- `main.py`：命令行入口
- `api.py`：FastAPI REST/SSE 服务入口
- `agent.py`：LangGraph State、节点、边和 Text2SQL 工作流
- `llm.py`：DeepSeek API 调用
- `database.py`：PostgreSQL/SQLite Schema 获取与只读查询执行
- `mcp_server.py`：三个数据库 MCP 工具和 stdio Server 入口
- `mcp_client.py`：供 LangGraph 使用的 MCP 数据库适配器
- `sql_guard.py`：SQL AST 校验与结果行数限制
- `schema_retriever.py`：Schema 语义检索、关系路径补全、业务规则与 Few-shot
- `docker-compose.yml`：PostgreSQL 17 本地服务
- `docker/postgres/init/`：表结构、索引和只读账号初始化
- `scripts/seed_ecommerce.py`：确定性电商数据生成器
- `scripts/download_chinook.py`：下载官方 Chinook 数据库
- `tests/`：不调用外部 API 的单元测试

## 安全边界

V2 采用多层防护：

- SQLGlot AST 仅放行单条 `SELECT` / `WITH` 查询
- 拒绝 DDL、DML、PRAGMA、多语句和 `load_extension`
- 自动添加 `LIMIT 100`，并将更大的 LIMIT 收紧为 100
- 查询超过 3 秒会被数据库中断
- PostgreSQL Agent 使用独立只读账号、只读事务和 `statement_timeout`
- SQLite 仍使用只读 URI 和 `query_only`

SQL Guard 不能替代生产环境的最小权限数据库账号；迁移 PostgreSQL 时仍需为 Agent 配置只读用户。

## SQL Reflection

- 只捕获已经通过 SQL Guard 后发生的数据库执行错误
- 修复提示包含用户问题、Schema、失败 SQL 和真实数据库错误
- 修复 SQL 必须再次经过 AST 安全校验
- 默认最多修复 3 次，达到上限后返回明确错误
- 安全校验失败不会进入 Reflection，避免模型尝试绕过 Guard
