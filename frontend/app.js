const API_BASE = "http://localhost:8000/api";
const SESSION_STORAGE_KEY = "chatSessionsV2";
const ACTIVE_SESSION_KEY = "activeChatSessionIdV2";
const MAX_SESSIONS = 30;
const MAX_MESSAGES_PER_SESSION = 120;

const app = document.getElementById("app");
const sidebarToggle = document.getElementById("sidebarToggle");

const welcomePanel = document.getElementById("welcomePanel");
const chat = document.getElementById("chat");
const panelFiles = document.getElementById("panelFiles");
const panelStatus = document.getElementById("panelStatus");
const composerWrap = document.getElementById("composerWrap");

const composer = document.getElementById("composer");
const input = document.getElementById("input");
const historyList = document.getElementById("historyList");

const menuFiles = document.getElementById("menuFiles");
const menuStatus = document.getElementById("menuStatus");
const uploadArea = document.getElementById("uploadArea");
const fileFeedback = document.getElementById("fileFeedback");

let chatSessions = loadSessions();
let activeSessionId = localStorage.getItem(ACTIVE_SESSION_KEY) || null;

function loadSessions() {
  try {
    const parsed = JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((s) => s && typeof s.id === "string" && Array.isArray(s.messages))
      .map((s) => ({
        id: s.id,
        title: typeof s.title === "string" && s.title.trim() ? s.title : "新会话",
        updatedAt: Number.isFinite(s.updatedAt) ? s.updatedAt : Date.now(),
        messages: s.messages
          .filter((m) => m && typeof m.type === "string")
          .slice(-MAX_MESSAGES_PER_SESSION),
      }))
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, MAX_SESSIONS);
  } catch {
    return [];
  }
}

function persistSessions() {
  chatSessions.sort((a, b) => b.updatedAt - a.updatedAt);
  chatSessions = chatSessions.slice(0, MAX_SESSIONS);
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(chatSessions));

  if (activeSessionId) {
    localStorage.setItem(ACTIVE_SESSION_KEY, activeSessionId);
  } else {
    localStorage.removeItem(ACTIVE_SESSION_KEY);
  }
}

function getActiveSession() {
  if (!activeSessionId) return null;
  return chatSessions.find((s) => s.id === activeSessionId) || null;
}

function summarizeTitle(text) {
  const clean = String(text).replace(/\s+/g, " ").trim();
  if (!clean) return "新会话";
  return clean.length > 16 ? `${clean.slice(0, 16)}...` : clean;
}

function createSession(firstQuery = "") {
  const session = {
    id: `s_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    title: summarizeTitle(firstQuery),
    updatedAt: Date.now(),
    messages: [],
  };
  chatSessions.unshift(session);
  activeSessionId = session.id;
  persistSessions();
  return session;
}

function ensureActiveSession(firstQuery = "") {
  const current = getActiveSession();
  if (current) return current;
  return createSession(firstQuery);
}

function touchSession(session) {
  session.updatedAt = Date.now();
  persistSessions();
}

function setMenuActive(target) {
  [menuFiles, menuStatus].forEach((el) => el.classList.remove("active"));
  if (target === "files") menuFiles.classList.add("active");
  if (target === "status") menuStatus.classList.add("active");
}

function hidePanels() {
  panelFiles.classList.add("hidden");
  panelStatus.classList.add("hidden");
}

function showWelcome() {
  hidePanels();
  welcomePanel.style.display = "";
  chat.style.display = "none";
  composerWrap.classList.remove("hidden");
  setMenuActive(null);
}

function showChat() {
  hidePanels();
  welcomePanel.style.display = "none";
  chat.style.display = "block";
  composerWrap.classList.remove("hidden");
  setMenuActive(null);
}

function showPanel(view) {
  welcomePanel.style.display = "none";
  chat.style.display = "none";
  composerWrap.classList.add("hidden");

  panelFiles.classList.toggle("hidden", view !== "files");
  panelStatus.classList.toggle("hidden", view !== "status");
  setMenuActive(view);

  if (view === "files") {
    loadDocumentList();
  }

  if (view === "status") {
    checkSystemStatus();
  }
}

function restoreConversationView() {
  const session = getActiveSession();
  if (session && session.messages.length > 0) {
    renderSessionMessages(session);
    showChat();
  } else {
    showWelcome();
  }
}

let fileFeedbackTimer = null;

function showFileFeedback(message, type = "info", autoHideMs = 4500) {
  if (!fileFeedback) return;
  if (fileFeedbackTimer) {
    clearTimeout(fileFeedbackTimer);
    fileFeedbackTimer = null;
  }
  fileFeedback.className = `file-feedback ${type}`;
  fileFeedback.textContent = message;
  fileFeedback.classList.remove("hidden");

  if (autoHideMs > 0) {
    fileFeedbackTimer = setTimeout(() => {
      fileFeedback.classList.add("hidden");
    }, autoHideMs);
  }
}

function setUploadBusy(isBusy) {
  const fileInput = document.getElementById("docFileInput");
  if (fileInput) {
    fileInput.disabled = isBusy;
  }
  if (uploadArea) {
    uploadArea.classList.toggle("uploading", isBusy);
  }
}

function escapeHtml(text) {
  const map = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };
  return String(text).replace(/[&<>"']/g, (m) => map[m]);
}

function nl2br(text) {
  return escapeHtml(text).replace(/\n/g, "<br>");
}

function buildAssistantHtml(answer, citations) {
  let html = `<div class="answer-title">助手回答</div><p>${nl2br(answer || "已收到你的消息。")}</p>`;

  if (Array.isArray(citations) && citations.length > 0) {
    html += `
      <details class="citation-wrap">
        <summary class="citation-toggle">
          <span>引用来源（${citations.length}）</span>
          <span class="citation-toggle-text">点击展开/收起</span>
        </summary>
        <div class="citation-list">
    `;
    citations.forEach((c, index) => {
      const lineStart = Number.isFinite(c.line_start) ? c.line_start : "-";
      const lineEnd = Number.isFinite(c.line_end) ? c.line_end : "-";
      const score = Number.isFinite(c.similarity_score) ? `${(c.similarity_score * 100).toFixed(1)}%` : "--";
      html += `
        <div class="citation">
          <div class="citation-meta">
            <span class="source-badge">来源${index + 1}</span>
            <span class="source-auth">真实来源</span>
            <span class="citation-origin">${escapeHtml(c.file_name || "来源")} · ${lineStart}-${lineEnd} · ${score}</span>
          </div>
          <div class="citation-snippet">${nl2br((c.snippet || "").trim())}</div>
        </div>
      `;
    });
    html += `
        </div>
      </details>
    `;
  }

  return html;
}

function appendMessage(role, html, shouldScroll = true) {
  const el = document.createElement("article");
  el.className = `msg ${role}`.trim();
  el.innerHTML = html;
  chat.appendChild(el);

  if (shouldScroll) {
    chat.scrollTop = chat.scrollHeight;
  }
  return el;
}

function pushMessageToActive(message) {
  const session = ensureActiveSession();
  session.messages.push(message);
  if (session.messages.length > MAX_MESSAGES_PER_SESSION) {
    session.messages = session.messages.slice(-MAX_MESSAGES_PER_SESSION);
  }

  if (message.type === "user" && (!session.title || session.title === "新会话")) {
    session.title = summarizeTitle(message.text || "");
  }

  touchSession(session);
  renderHistory();
}

function appendUserMessage(text, save = true) {
  appendMessage("user", `<p>${nl2br(text)}</p>`);
  if (save) {
    pushMessageToActive({ type: "user", text });
  }
}

function appendLoadingMessage() {
  return appendMessage("loading-msg", `<p>思考中...</p>`);
}

function appendErrorMessage(message, save = false) {
  appendMessage("error-msg", `<p>${nl2br(message)}</p>`);
  if (save) {
    pushMessageToActive({ type: "error", text: message });
  }
}

function appendChatResponse(response, save = true) {
  const citations = Array.isArray(response.citations)
    ? response.citations.map((c) => ({
        file_name: c.file_name,
        line_start: c.line_start,
        line_end: c.line_end,
        similarity_score: c.similarity_score,
        snippet: c.snippet,
      }))
    : [];

  const answer = response.answer || "已收到你的消息。";
  appendMessage("", buildAssistantHtml(answer, citations));

  if (save) {
    pushMessageToActive({ type: "assistant", answer, citations });
  }
}

function renderSessionMessages(session) {
  chat.innerHTML = "";

  session.messages.forEach((msg) => {
    if (msg.type === "user") {
      appendMessage("user", `<p>${nl2br(msg.text || "")}</p>`, false);
      return;
    }
    if (msg.type === "assistant") {
      appendMessage("", buildAssistantHtml(msg.answer || "", msg.citations || []), false);
      return;
    }
    appendMessage("error-msg", `<p>${nl2br(msg.text || "")}</p>`, false);
  });

  chat.scrollTop = chat.scrollHeight;
}

function renderHistory() {
  historyList.innerHTML = "";

  if (chatSessions.length === 0) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "暂无历史记录";
    historyList.appendChild(empty);
    return;
  }

  chatSessions.forEach((session) => {
    const row = document.createElement("div");
    row.className = "history-entry";
    if (session.id === activeSessionId) {
      row.classList.add("active");
    }

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "history-item";
    btn.textContent = session.title;
    btn.title = session.title;
    btn.addEventListener("click", () => {
      activeSessionId = session.id;
      persistSessions();
      renderHistory();
      renderSessionMessages(session);
      showChat();
      input.focus();
    });

    const del = document.createElement("button");
    del.type = "button";
    del.className = "history-delete";
    del.setAttribute("aria-label", "删除历史会话");
    del.title = "删除历史会话";
    del.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
        <path fill="currentColor" d="M9 3h6l1 2h4v2H4V5h4l1-2Zm1 7h2v8h-2v-8Zm4 0h2v8h-2v-8ZM7 10h2v8H7v-8Z"/>
      </svg>
    `;
    del.addEventListener("click", (event) => {
      event.stopPropagation();
      chatSessions = chatSessions.filter((s) => s.id !== session.id);
      if (activeSessionId === session.id) {
        activeSessionId = null;
        chat.innerHTML = "";
      }
      persistSessions();
      renderHistory();
      restoreConversationView();
    });

    row.appendChild(btn);
    row.appendChild(del);
    historyList.appendChild(row);
  });
}

async function executeSearch(query) {
  const session = ensureActiveSession(query);
  activeSessionId = session.id;
  persistSessions();
  renderHistory();

  showChat();
  appendUserMessage(query, true);
  const loadingNode = appendLoadingMessage();

  try {
    const response = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        top_k_documents: 3,
        top_k_paragraphs: 8,
      }),
    });

    loadingNode.remove();

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      appendErrorMessage(`请求失败 (${response.status})：${err.detail || "未知错误"}`, true);
      return;
    }

    const data = await response.json();
    appendChatResponse(data, true);
  } catch (err) {
    loadingNode.remove();
    appendErrorMessage(`无法连接到后端服务：${err.message}`, true);
  }
}

function appendDocToList(data) {
  const docList = document.getElementById("docList");
  const docId = String(data.doc_id || "");
  const existed = docList.querySelector(`[data-doc-id="${docId}"]`);
  if (existed) {
    existed.remove();
  }

  const el = document.createElement("div");
  el.className = "doc-item";
  el.dataset.docId = docId;

  const shortId = escapeHtml(String(data.doc_id || "")).slice(0, 8);
  const paragraphCount = Number.isFinite(data.paragraphs_indexed) ? data.paragraphs_indexed : 0;
  const lineCount = Number.isFinite(data.total_lines) ? data.total_lines : 0;
  const fileName = escapeHtml(String(data.file_name || ""));

  el.innerHTML = `
    <div class="doc-info">
      <strong title="${fileName || shortId}">${fileName || shortId || "未知文件"}</strong>
      <span>${paragraphCount} 段 · ${lineCount} 行</span>
    </div>
    <button class="doc-delete" type="button">删除</button>
  `;

  const deleteBtn = el.querySelector(".doc-delete");
  deleteBtn.addEventListener("click", async () => {
    try {
      await fetch(`${API_BASE}/documents/${encodeURIComponent(data.doc_id)}`, { method: "DELETE" });
      el.remove();
      showEmptyDocHint();
    } catch (err) {
      appendErrorMessage(`删除失败：${err.message}`);
    }
  });

  docList.appendChild(el);
}

function showEmptyDocHint() {
  const docList = document.getElementById("docList");
  if (docList.children.length === 0) {
    docList.innerHTML = `<div class="doc-item"><div class="doc-info"><strong>暂无已上传文件</strong><span>上传后会显示在这里</span></div></div>`;
  }
}

async function handleDocUpload(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE}/documents/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `上传失败 (${response.status})`);
  }

  const data = await response.json();
  const docList = document.getElementById("docList");
  const hint = docList.querySelector(".doc-item");
  if (hint && hint.textContent.includes("暂无已上传文件")) {
    docList.innerHTML = "";
  }
  appendDocToList(data);
}

async function loadDocumentList() {
  const docList = document.getElementById("docList");
  docList.innerHTML = "";

  try {
    const response = await fetch(`${API_BASE}/documents?limit=100`);
    if (!response.ok) {
      throw new Error(`加载失败 (${response.status})`);
    }
    const list = await response.json();
    if (!Array.isArray(list) || list.length === 0) {
      showEmptyDocHint();
      return;
    }
    list.forEach((item) => appendDocToList(item));
  } catch (err) {
    docList.innerHTML =
      `<div class="doc-item"><div class="doc-info"><strong>读取失败</strong><span>${escapeHtml(err.message || "请稍后重试")}</span></div></div>`;
  }
}

async function checkSystemStatus() {
  const setStatus = (id, ready, text) => {
    const item = document.getElementById(id);
    if (!item) return;
    const dot = item.querySelector(".status-dot");
    const label = item.querySelector(".status-text");
    dot.className = `status-dot ${ready ? "ready" : "error"}`;
    label.textContent = text;
  };

  try {
    const response = await fetch(`${API_BASE}/health`);
    if (!response.ok) throw new Error("health request failed");

    const data = await response.json();
    setStatus("statusPG", !!data.postgresql_ready, data.postgresql_ready ? "就绪" : "未就绪");
    setStatus("statusQdrant", !!data.qdrant_ready, data.qdrant_ready ? "就绪" : "未就绪");
    setStatus("statusEmbedding", !!data.embedding_model_ready, data.embedding_model_ready ? "就绪" : "未就绪");
    setStatus("statusReranker", !!data.reranker_model_ready, data.reranker_model_ready ? "就绪" : "未就绪");
  } catch (err) {
    ["statusPG", "statusQdrant", "statusEmbedding", "statusReranker"].forEach((id) => {
      const item = document.getElementById(id);
      if (!item) return;
      const dot = item.querySelector(".status-dot");
      const label = item.querySelector(".status-text");
      dot.className = "status-dot error";
      label.textContent = "后端未连接";
    });
  }
}

renderHistory();
showEmptyDocHint();

const activeSession = getActiveSession();
if (activeSession && activeSession.messages.length > 0) {
  renderSessionMessages(activeSession);
  showChat();
} else {
  showWelcome();
}

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const query = input.value.trim();
  if (!query) return;
  executeSearch(query);
  input.value = "";
});

document.querySelectorAll(".suggestions button").forEach((btn) => {
  btn.addEventListener("click", () => {
    input.value = btn.textContent || "";
    input.focus();
  });
});

document.getElementById("newChatBtn").addEventListener("click", () => {
  activeSessionId = null;
  persistSessions();
  chat.innerHTML = "";
  renderHistory();
  showWelcome();
  input.focus();
});

menuFiles.addEventListener("click", () => showPanel("files"));
menuStatus.addEventListener("click", () => showPanel("status"));

document.querySelectorAll(".panel-close").forEach((btn) => {
  btn.addEventListener("click", restoreConversationView);
});

document.getElementById("docFileInput").addEventListener("change", async (event) => {
  const files = event.target.files;
  if (!files || files.length === 0) return;

  setUploadBusy(true);
  showFileFeedback(`正在上传 ${files.length} 个文件...`, "info", 0);

  let successCount = 0;
  let failureCount = 0;

  for (const file of files) {
    try {
      await handleDocUpload(file);
      successCount += 1;
      showFileFeedback(`上传成功：${file.name}`, "success", 2200);
    } catch (err) {
      failureCount += 1;
      showFileFeedback(`${file.name} 上传失败：${err.message}`, "error", 8000);
    }
  }

  if (successCount > 0) {
    await loadDocumentList();
  }

  if (failureCount === 0) {
    showFileFeedback(`上传完成：成功 ${successCount} 个`, "success", 3500);
  } else {
    showFileFeedback(`上传完成：成功 ${successCount} 个，失败 ${failureCount} 个`, "error", 9000);
  }

  setUploadBusy(false);
  event.target.value = "";
});

document.getElementById("refreshStatusBtn").addEventListener("click", checkSystemStatus);

document.getElementById("bootstrapBtn").addEventListener("click", async () => {
  try {
    const response = await fetch(`${API_BASE}/bootstrap`, { method: "POST" });
    if (!response.ok) {
      throw new Error(`请求失败 (${response.status})`);
    }
    await response.json();
    checkSystemStatus();
  } catch (err) {
    appendErrorMessage(`初始化失败：${err.message}`);
  }
});

sidebarToggle.addEventListener("click", () => {
  app.classList.toggle("sidebar-open");
});

window.addEventListener("resize", () => {
  if (window.innerWidth > 900) {
    app.classList.remove("sidebar-open");
  }
});
