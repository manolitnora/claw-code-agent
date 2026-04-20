"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const State = {
  serverState: null,
  sessions: [],
  slashCommands: [],
  skills: [],
  activeSessionId: null,   // the session we will resume on next send
  isBusy: false,
  paletteMode: null,       // "slash" | "skills" | null
  // Pasted content keyed by ref id.  Cleared after each send.  Mirrors the
  // npm front-end's `[Pasted text #N]` collapsing — large pastes never sit
  // inline in the textarea, only the placeholder ref does.
  pastedContents: {},
  nextPasteId: 1,
};

// Paste larger than this many characters gets collapsed to a [Pasted text #N]
// reference.  500 is what the npm front-end uses for its truncation threshold.
const PASTE_COLLAPSE_THRESHOLD = 500;

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const $ = (sel) => document.querySelector(sel);
const els = {
  chat: $("#chat"),
  welcome: $("#welcome"),
  input: $("#prompt-input"),
  sendBtn: $("#send-btn"),
  sessionList: $("#session-list"),
  newSessionBtn: $("#new-session-btn"),
  settingsForm: $("#settings-form"),
  statusDot: $("#status-dot"),
  statusText: $("#status-text"),
  cwdMeta: $("#cwd-meta"),
  usageMeta: $("#usage-meta"),
  slashBtn: $("#slash-btn"),
  skillsBtn: $("#skills-btn"),
  clearBtn: $("#clear-btn"),
  palette: $("#palette"),
  paletteSearch: $("#palette-search"),
  paletteList: $("#palette-list"),
  paletteClose: $("#palette-close"),
  pasteChips: $("#paste-chips"),
};

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
async function apiGet(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body == null ? "{}" : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok && !data.error) {
    throw new Error(data.detail || `${r.status} ${r.statusText}`);
  }
  return data;
}

// ---------------------------------------------------------------------------
// Markdown rendering (small, dependency-free)
// ---------------------------------------------------------------------------
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMarkdown(md) {
  if (md == null) return "";
  // Pull fenced code blocks out first so their contents are not parsed.
  const codeBlocks = [];
  let text = String(md).replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_, lang, body) => {
    const idx = codeBlocks.length;
    codeBlocks.push({ lang, body });
    return `\u0000CODE${idx}\u0000`;
  });
  text = escapeHtml(text);
  // Headings
  text = text.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  text = text.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  text = text.replace(/^# (.+)$/gm, "<h1>$1</h1>");
  // Bold / italic
  text = text.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/(^|\W)\*([^*\n]+)\*(\W|$)/g, "$1<em>$2</em>$3");
  // Inline code
  text = text.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  // Links
  text = text.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>'
  );
  // Lists (simple, line-based)
  text = text.replace(/(?:^|\n)((?:- .+\n?)+)/g, (_, block) => {
    const items = block
      .trim()
      .split(/\n/)
      .map((l) => `<li>${l.replace(/^- /, "")}</li>`)
      .join("");
    return `\n<ul>${items}</ul>\n`;
  });
  text = text.replace(/(?:^|\n)((?:\d+\. .+\n?)+)/g, (_, block) => {
    const items = block
      .trim()
      .split(/\n/)
      .map((l) => `<li>${l.replace(/^\d+\. /, "")}</li>`)
      .join("");
    return `\n<ol>${items}</ol>\n`;
  });
  // Paragraphs (split on blank lines)
  text = text
    .split(/\n{2,}/)
    .map((chunk) => {
      const t = chunk.trim();
      if (!t) return "";
      if (/^<(h\d|ul|ol|pre|blockquote)/.test(t)) return t;
      return `<p>${t.replace(/\n/g, "<br/>")}</p>`;
    })
    .join("\n");
  // Restore code blocks
  text = text.replace(/\u0000CODE(\d+)\u0000/g, (_, idx) => {
    const { lang, body } = codeBlocks[Number(idx)];
    const langClass = lang ? ` class="lang-${escapeHtml(lang)}"` : "";
    return `<pre><code${langClass}>${escapeHtml(body)}</code></pre>`;
  });
  return text;
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------
function setStatus(state, text) {
  els.statusDot.classList.remove("busy", "error");
  if (state === "busy") els.statusDot.classList.add("busy");
  if (state === "error") els.statusDot.classList.add("error");
  els.statusText.textContent = text;
}

function setBusy(busy) {
  State.isBusy = busy;
  els.sendBtn.disabled = busy;
  els.input.disabled = busy;
  if (busy) setStatus("busy", "Working…");
  else setStatus("ready", "Ready");
}

function clearChat() {
  els.chat.innerHTML = "";
  if (els.welcome) {
    els.chat.appendChild(els.welcome);
  }
}

function hideWelcome() {
  if (els.welcome && els.welcome.parentElement) {
    els.welcome.remove();
  }
}

function avatarFor(role) {
  if (role === "user") return "U";
  if (role === "assistant") return "AI";
  if (role === "tool") return "⚙";
  if (role === "error") return "!";
  return "•";
}

function appendMessage({ role, content, html }) {
  hideWelcome();
  const wrap = document.createElement("div");
  wrap.className = `message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = avatarFor(role);

  const body = document.createElement("div");
  body.className = "body";
  if (html != null) {
    body.innerHTML = html;
  } else if (role === "user") {
    body.textContent = content;
  } else {
    body.innerHTML = renderMarkdown(content);
  }
  wrap.appendChild(avatar);
  wrap.appendChild(body);
  els.chat.appendChild(wrap);
  els.chat.scrollTop = els.chat.scrollHeight;
  return wrap;
}

function appendToolCall({ name, args, result, isError }) {
  hideWelcome();
  const wrap = document.createElement("div");
  wrap.className = "message tool";
  wrap.innerHTML = `<div class="avatar">⚙</div>`;

  const body = document.createElement("div");
  body.className = "body";

  const details = document.createElement("details");
  details.className = "tool-call";

  const summary = document.createElement("summary");
  const argsPreview = typeof args === "string" ? args : JSON.stringify(args);
  summary.innerHTML = `
    <span class="tool-name">${escapeHtml(name)}</span>
    <span class="tool-args">${escapeHtml(argsPreview).slice(0, 240)}</span>
  `;
  details.appendChild(summary);

  const inner = document.createElement("div");
  inner.className = "tool-body";
  inner.innerHTML = `
    <div class="label">Arguments</div>
    <pre>${escapeHtml(typeof args === "string" ? args : JSON.stringify(args, null, 2))}</pre>
    <div class="label">Result${isError ? " (error)" : ""}</div>
    <pre>${escapeHtml(result || "")}</pre>
  `;
  details.appendChild(inner);
  body.appendChild(details);

  wrap.appendChild(body);
  els.chat.appendChild(wrap);
  els.chat.scrollTop = els.chat.scrollHeight;
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
function applyServerState(state) {
  State.serverState = state;
  els.settingsForm.model.value = state.model || "";
  els.settingsForm.base_url.value = state.base_url || "";
  els.settingsForm.cwd.value = state.cwd || "";
  els.settingsForm.allow_shell.checked = !!state.allow_shell;
  els.settingsForm.allow_write.checked = !!state.allow_write;
  els.cwdMeta.textContent = `cwd: ${state.cwd || "?"}`;
}

async function loadServerState() {
  try {
    const state = await apiGet("/api/state");
    applyServerState(state);
  } catch (e) {
    setStatus("error", `state: ${e.message}`);
  }
}

async function saveSettings(ev) {
  ev.preventDefault();
  const fd = new FormData(els.settingsForm);
  const payload = {
    model: fd.get("model") || "",
    base_url: fd.get("base_url") || "",
    cwd: fd.get("cwd") || "",
    allow_shell: els.settingsForm.allow_shell.checked,
    allow_write: els.settingsForm.allow_write.checked,
  };
  try {
    setStatus("busy", "Saving settings…");
    const state = await apiPost("/api/state", payload);
    applyServerState(state);
    setStatus("ready", "Settings saved");
  } catch (e) {
    setStatus("error", `save: ${e.message}`);
  }
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------
async function loadSessions() {
  try {
    const sessions = await apiGet("/api/sessions");
    State.sessions = sessions;
    renderSessions();
  } catch (e) {
    els.sessionList.innerHTML = `<div class="empty-state">${escapeHtml(e.message)}</div>`;
  }
}

function renderSessions() {
  els.sessionList.innerHTML = "";
  if (!State.sessions.length) {
    els.sessionList.innerHTML = `<div class="empty-state">No saved sessions yet.</div>`;
    return;
  }
  for (const s of State.sessions) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "session-item";
    if (s.session_id === State.activeSessionId) item.classList.add("active");
    const preview = s.preview || "(no preview)";
    item.innerHTML = `
      <div class="session-preview">${escapeHtml(preview)}</div>
      <div class="session-meta">${s.turns} turns · ${s.tool_calls} tools</div>
    `;
    item.addEventListener("click", () => openSession(s.session_id));
    els.sessionList.appendChild(item);
  }
}

async function openSession(sessionId) {
  try {
    setStatus("busy", "Loading session…");
    const session = await apiGet(`/api/sessions/${encodeURIComponent(sessionId)}`);
    State.activeSessionId = sessionId;
    clearChat();
    for (const msg of session.messages) {
      renderTranscriptEntry(msg);
    }
    renderSessions();
    setStatus("ready", `Session ${sessionId.slice(0, 8)}…`);
  } catch (e) {
    setStatus("error", `session: ${e.message}`);
  }
}

function newSession() {
  State.activeSessionId = null;
  clearChat();
  clearPasteStash();
  renderSessions();
  setStatus("ready", "New chat");
  els.input.focus();
}

// ---------------------------------------------------------------------------
// Transcript rendering
// ---------------------------------------------------------------------------
function renderTranscriptEntry(entry) {
  if (!entry || !entry.role) return;
  if (entry.role === "system") return;
  if (entry.role === "user") {
    appendMessage({ role: "user", content: entry.content || "" });
    return;
  }
  if (entry.role === "assistant") {
    if (entry.content && entry.content.trim()) {
      appendMessage({ role: "assistant", content: entry.content });
    }
    if (Array.isArray(entry.tool_calls)) {
      for (const tc of entry.tool_calls) {
        const name = tc?.function?.name || tc?.name || "tool";
        let args = tc?.function?.arguments ?? tc?.arguments ?? "";
        try {
          if (typeof args === "string") args = JSON.parse(args);
        } catch {}
        appendToolCall({ name, args, result: "(pending — see following tool message)" });
      }
    }
    return;
  }
  if (entry.role === "tool") {
    const name = entry.name || "tool";
    const meta = entry.metadata || {};
    appendToolCall({
      name,
      args: meta.action || "",
      result: entry.content || "",
      isError: meta.ok === false,
    });
    return;
  }
}

// ---------------------------------------------------------------------------
// Slash commands / skills palette
// ---------------------------------------------------------------------------
async function loadSlashCommands() {
  try {
    State.slashCommands = await apiGet("/api/slash-commands");
  } catch (e) {
    State.slashCommands = [];
  }
}

async function loadSkills() {
  try {
    State.skills = await apiGet("/api/skills");
  } catch (e) {
    State.skills = [];
  }
}

function openPalette(mode) {
  State.paletteMode = mode;
  els.palette.classList.remove("hidden");
  els.paletteSearch.value = "";
  renderPalette("");
  els.paletteSearch.focus();
}

function closePalette() {
  els.palette.classList.add("hidden");
  State.paletteMode = null;
}

function renderPalette(filter) {
  const items = State.paletteMode === "skills" ? State.skills : State.slashCommands;
  const f = (filter || "").toLowerCase().trim();
  els.paletteList.innerHTML = "";
  for (const item of items) {
    const display =
      State.paletteMode === "skills"
        ? { name: item.name, desc: item.description }
        : { name: `/${item.primary}`, desc: item.description };
    if (f && !display.name.toLowerCase().includes(f) && !display.desc.toLowerCase().includes(f))
      continue;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "palette-item";
    btn.innerHTML = `<span class="palette-name">${escapeHtml(display.name)}</span><span class="palette-desc">${escapeHtml(display.desc || "")}</span>`;
    btn.addEventListener("click", () => {
      if (State.paletteMode === "skills") {
        els.input.value = `Use the ${item.name} skill`;
      } else {
        els.input.value = `/${item.primary} `;
      }
      closePalette();
      autoSizeInput();
      els.input.focus();
    });
    els.paletteList.appendChild(btn);
  }
  if (!els.paletteList.children.length) {
    els.paletteList.innerHTML = `<div class="empty-state" style="padding:10px;">No matches.</div>`;
  }
}

// ---------------------------------------------------------------------------
// Paste-ref handling
// ---------------------------------------------------------------------------
function countNewlines(text) {
  // Match npm's getPastedTextRefNumLines: count of \r\n / \r / \n.
  const m = text.match(/\r\n|\r|\n/g);
  return m ? m.length : 0;
}

function formatPastedRef(id, lines) {
  return lines === 0 ? `[Pasted text #${id}]` : `[Pasted text #${id} +${lines} lines]`;
}

function renderPasteChips() {
  els.pasteChips.innerHTML = "";
  const ids = Object.keys(State.pastedContents)
    .map(Number)
    .sort((a, b) => a - b);
  if (!ids.length) {
    els.pasteChips.hidden = true;
    return;
  }
  els.pasteChips.hidden = false;
  for (const id of ids) {
    const entry = State.pastedContents[id];
    const chip = document.createElement("span");
    chip.className = "paste-chip";
    chip.innerHTML = `
      <span class="paste-chip-label">[Pasted text #${id}]</span>
      <span class="paste-chip-meta">${entry.lines} line${entry.lines === 1 ? "" : "s"} · ${entry.content.length} chars</span>
      <button type="button" class="paste-chip-remove" title="Remove">✕</button>
    `;
    chip.querySelector(".paste-chip-remove").addEventListener("click", () => {
      // Drop both the stash entry and any inline ref so a later send can't
      // refer to a paste the server doesn't have.
      delete State.pastedContents[id];
      const ref = formatPastedRef(id, entry.lines);
      els.input.value = els.input.value.split(ref).join("");
      autoSizeInput();
      renderPasteChips();
      els.input.focus();
    });
    els.pasteChips.appendChild(chip);
  }
}

function clearPasteStash() {
  State.pastedContents = {};
  State.nextPasteId = 1;
  renderPasteChips();
}

function handlePaste(ev) {
  const cd = ev.clipboardData;
  if (!cd) return;
  const text = cd.getData("text/plain");
  if (!text || text.length < PASTE_COLLAPSE_THRESHOLD) return;
  ev.preventDefault();

  const id = State.nextPasteId++;
  const lines = countNewlines(text);
  State.pastedContents[id] = { type: "text", content: text, lines };
  const ref = formatPastedRef(id, lines);

  // Splice at the current selection so the placeholder lands where the user
  // pasted, just like a normal paste would.
  const ta = els.input;
  const start = ta.selectionStart ?? ta.value.length;
  const end = ta.selectionEnd ?? ta.value.length;
  ta.value = ta.value.slice(0, start) + ref + ta.value.slice(end);
  const caret = start + ref.length;
  ta.setSelectionRange(caret, caret);

  autoSizeInput();
  renderPasteChips();
}

// ---------------------------------------------------------------------------
// Composer
// ---------------------------------------------------------------------------
function autoSizeInput() {
  els.input.style.height = "auto";
  els.input.style.height = Math.min(els.input.scrollHeight, 200) + "px";
}

async function send() {
  if (State.isBusy) return;
  const prompt = els.input.value.trim();
  if (!prompt) return;
  appendMessage({ role: "user", content: prompt });
  els.input.value = "";
  autoSizeInput();
  setBusy(true);
  try {
    const pastedContents = {};
    for (const [id, entry] of Object.entries(State.pastedContents)) {
      pastedContents[id] = { type: entry.type, content: entry.content };
    }
    const payload = {
      prompt,
      resume_session_id: State.activeSessionId || null,
      pasted_contents: pastedContents,
    };
    const data = await apiPost("/api/chat", payload);
    if (data.error) {
      appendMessage({ role: "error", content: `${data.error_type}: ${data.error}` });
      setStatus("error", "Error");
    } else {
      // Render tool calls + final response from the transcript so the user
      // sees what the agent actually did, not just the final reply.
      renderRunResult(data);
      State.activeSessionId = data.session_id || State.activeSessionId;
      els.usageMeta.textContent =
        `turns: ${data.turns}  ·  tools: ${data.tool_calls}` +
        (data.usage?.total_tokens
          ? `  ·  tokens: ${data.usage.total_tokens}`
          : "");
      clearPasteStash();
      await loadSessions();
    }
  } catch (e) {
    appendMessage({ role: "error", content: e.message });
    setStatus("error", "Error");
  } finally {
    setBusy(false);
    els.input.focus();
  }
}

function renderRunResult(data) {
  // We already rendered the user prompt. The transcript starts with system +
  // user + assistant turns; we want to show: any tool messages that happened
  // since the last user message, then the final assistant response.
  const transcript = data.transcript || [];
  let lastUserIndex = -1;
  for (let i = transcript.length - 1; i >= 0; i--) {
    if (transcript[i].role === "user") {
      lastUserIndex = i;
      break;
    }
  }
  const tail = transcript.slice(lastUserIndex + 1);
  for (const entry of tail) {
    if (entry.role === "assistant") {
      // Only render if it has visible content; tool_calls already rendered.
      if (Array.isArray(entry.tool_calls) && entry.tool_calls.length) {
        // Skip — corresponding tool messages will follow.
        continue;
      }
    }
    renderTranscriptEntry(entry);
  }
  // Always show the canonical final output if it isn't already present.
  const lastMsg = els.chat.querySelector(".message.assistant:last-of-type .body");
  if (!lastMsg || lastMsg.textContent.trim() !== (data.final_output || "").trim()) {
    if (data.final_output && data.final_output.trim()) {
      appendMessage({ role: "assistant", content: data.final_output });
    }
  }
}

// ---------------------------------------------------------------------------
// Wire up
// ---------------------------------------------------------------------------
function bind() {
  els.input.addEventListener("input", autoSizeInput);
  els.input.addEventListener("paste", handlePaste);
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  els.sendBtn.addEventListener("click", send);
  els.newSessionBtn.addEventListener("click", newSession);
  els.settingsForm.addEventListener("submit", saveSettings);
  els.slashBtn.addEventListener("click", () => openPalette("slash"));
  els.skillsBtn.addEventListener("click", () => openPalette("skills"));
  els.clearBtn.addEventListener("click", async () => {
    try {
      setStatus("busy", "Clearing…");
      await apiPost("/api/clear", {});
      newSession();
      setStatus("ready", "Cleared");
    } catch (e) {
      setStatus("error", e.message);
    }
  });
  els.paletteClose.addEventListener("click", closePalette);
  els.palette.addEventListener("click", (e) => {
    if (e.target === els.palette) closePalette();
  });
  els.paletteSearch.addEventListener("input", (e) => renderPalette(e.target.value));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !els.palette.classList.contains("hidden")) {
      closePalette();
    }
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      openPalette("slash");
    }
  });
}

async function init() {
  bind();
  setStatus("ready", "Ready");
  await Promise.all([
    loadServerState(),
    loadSessions(),
    loadSlashCommands(),
    loadSkills(),
  ]);
  els.input.focus();
}

init();
