const form = document.querySelector("#queryForm");
const question = document.querySelector("#question");
const submitButton = document.querySelector("#submitButton");
const submitText = document.querySelector("#submitText");
const workspace = document.querySelector("#workspace");
const trace = document.querySelector("#trace");
const elapsed = document.querySelector("#elapsed");
const answerCard = document.querySelector("#answerCard");
const answer = document.querySelector("#answer");
const sqlCard = document.querySelector("#sqlCard");
const sql = document.querySelector("#sql");
const sqlMeta = document.querySelector("#sqlMeta");
const resultCard = document.querySelector("#resultCard");
const resultTable = document.querySelector("#resultTable");
const rowCount = document.querySelector("#rowCount");
const errorCard = document.querySelector("#errorCard");
const errorMessage = document.querySelector("#errorMessage");
const systemState = document.querySelector("#systemState");
const systemStateText = document.querySelector("#systemStateText");

let timer = null;
let startedAt = 0;

async function checkHealth() {
  try {
    const response = await fetch("/api/health", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error();
    const data = await response.json();
    systemState.className = "system-state online";
    systemStateText.textContent = `${data.database.toUpperCase()} 已连接`;
  } catch {
    systemState.className = "system-state offline";
    systemStateText.textContent = "服务不可用";
  }
}

function resetOutput() {
  workspace.classList.remove("hidden");
  [answerCard, sqlCard, resultCard, errorCard].forEach((node) => node.classList.add("hidden"));
  trace.replaceChildren();
  resultTable.replaceChildren();
  answer.textContent = "";
  sql.textContent = "";
  startedAt = performance.now();
  elapsed.textContent = "0.0s";
  clearInterval(timer);
  timer = setInterval(() => {
    elapsed.textContent = `${((performance.now() - startedAt) / 1000).toFixed(1)}s`;
  }, 100);
}

function addTrace(message, stage) {
  trace.querySelectorAll("li.active").forEach((item) => {
    item.classList.remove("active");
    item.classList.add("done");
  });
  const item = document.createElement("li");
  item.className = "active";
  item.dataset.stage = stage || "unknown";
  item.textContent = message;
  trace.append(item);
}

function renderTable(rows) {
  resultCard.classList.remove("hidden");
  rowCount.textContent = `${rows.length} 行`;
  if (!rows.length) {
    const empty = document.createElement("caption");
    empty.className = "empty-result";
    empty.textContent = "查询成功，没有匹配的数据";
    resultTable.append(empty);
    return;
  }
  const columns = Object.keys(rows[0]);
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((column) => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = column;
    headRow.append(cell);
  });
  head.append(headRow);
  const body = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const cell = document.createElement("td");
      const value = row[column];
      cell.textContent = value === null ? "NULL" : typeof value === "object" ? JSON.stringify(value) : String(value);
      tr.append(cell);
    });
    body.append(tr);
  });
  resultTable.append(head, body);
}

function renderResult(data) {
  answer.textContent = data.answer;
  answerCard.classList.remove("hidden");
  sql.textContent = data.sql;
  sqlMeta.replaceChildren();
  const tables = document.createElement("span");
  tables.textContent = data.retrieved_tables?.length ? `Schema: ${data.retrieved_tables.join(", ")}` : "Schema: 完整上下文";
  const retries = document.createElement("span");
  retries.textContent = `自动修复: ${data.retry_count} 次`;
  sqlMeta.append(tables, retries);
  sqlCard.classList.remove("hidden");
  renderTable(data.rows || []);
  trace.querySelectorAll("li.active").forEach((item) => {
    item.classList.remove("active");
    item.classList.add("done");
  });
}

function showError(message) {
  errorMessage.textContent = message;
  errorCard.classList.remove("hidden");
}

function handleEvent(eventName, rawData) {
  if (!rawData || rawData === "[DONE]") return;
  let data;
  try { data = JSON.parse(rawData); } catch { return; }
  if (eventName === "progress") addTrace(data.message, data.stage);
  if (eventName === "result") renderResult(data);
  if (eventName === "error") showError(data.message || "分析失败，请稍后重试。");
}

async function consumeSse(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done }).replaceAll("\r\n", "\n");
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      let eventName = "message";
      const dataLines = [];
      block.split("\n").forEach((line) => {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      });
      handleEvent(eventName, dataLines.join("\n"));
    }
    if (done) break;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = question.value.trim();
  if (!value) return;
  resetOutput();
  submitButton.disabled = true;
  submitText.textContent = "分析中";
  workspace.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question: value }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `请求失败 (${response.status})`);
    }
    await consumeSse(response);
  } catch (error) {
    showError(error instanceof Error ? error.message : "网络连接中断。");
  } finally {
    clearInterval(timer);
    elapsed.textContent = `${((performance.now() - startedAt) / 1000).toFixed(1)}s`;
    submitButton.disabled = false;
    submitText.textContent = "开始分析";
  }
});

document.querySelectorAll(".example").forEach((button) => {
  button.addEventListener("click", () => {
    question.value = button.textContent.trim();
    question.focus();
  });
});

question.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) form.requestSubmit();
});

document.querySelector("#copySql").addEventListener("click", async (event) => {
  await navigator.clipboard.writeText(sql.textContent);
  event.currentTarget.textContent = "已复制";
  setTimeout(() => { event.currentTarget.textContent = "复制 SQL"; }, 1400);
});

checkHealth();
