import MarkdownIt from "./markdown-it-15.0.3.mjs";

const markdown = new MarkdownIt({ html: false, linkify: true });
const chat = document.getElementById("chat");
const transcript = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("gerry-question");
const sendButton = document.getElementById("send-message");
const retryButton = document.getElementById("retry-message");
const newChatButton = document.getElementById("new-chat");
const pendingQuestion = document.getElementById("pending-question");
const progress = document.getElementById("progress");
const error = document.getElementById("error");
const checkButton = document.getElementById("check-connection");
const connectionDot = document.getElementById("connection-dot");
const connectionMessage = document.getElementById("connection-message");

let messages = [];
let conversationId = null;
let retryPayload = null;
let sending = false;

async function checkConnection() {
  checkButton.hidden = true;
  connectionDot.className = "status-dot";
  connectionMessage.textContent = "Connecting to Gerry…";
  let connected = false;
  try {
    const response = await fetch("/health");
    connected = response.ok && (await response.json())?.status === "ok";
  } catch {
    // A failed health check leaves the retry button available.
  }
  connectionDot.classList.add(connected ? "ready" : "unavailable");
  connectionMessage.textContent = connected
    ? "Connected to Gerry"
    : "Can't connect to Gerry right now.";
  checkButton.hidden = connected;
  chat.hidden = !connected;
}

function updateControls() {
  input.disabled = sending || retryPayload !== null;
  sendButton.disabled = input.disabled || !input.value.trim();
  retryButton.hidden = retryPayload === null;
  newChatButton.hidden = messages.length === 0 && !retryPayload && error.hidden;
  newChatButton.disabled = sending;
}

function showError(message) {
  error.textContent = message;
  error.hidden = !message;
}

function renderAnswer(answer, turnNumber) {
  const article = document.createElement("article");
  article.className = "research-answer";
  article.setAttribute("aria-label", "Research answer");
  const heading = "\n## Sources\n";
  const boundary = answer.lastIndexOf(heading);
  const briefing = boundary < 0 ? answer : answer.slice(0, boundary);
  const sources = boundary < 0 ? "" : answer.slice(boundary + heading.length).trim();
  article.innerHTML = markdown.render(briefing);

  for (const table of article.querySelectorAll("table")) {
    const scroller = document.createElement("div");
    scroller.className = "comparison-scroll";
    scroller.setAttribute("role", "region");
    scroller.setAttribute("aria-label", "Coverage comparison");
    scroller.tabIndex = 0;
    table.before(scroller);
    scroller.append(table);
  }
  if (!sources) return article;

  const panel = document.createElement("details");
  panel.className = "research-sources";
  const summary = document.createElement("summary");
  summary.textContent = "Sources";
  panel.append(summary);
  panel.insertAdjacentHTML("beforeend", markdown.render(sources));

  const sourceIds = new Map();
  for (const list of panel.querySelectorAll(":scope > ol")) {
    Array.from(list.children).forEach((item, index) => {
      const number = String(list.start + index);
      item.id = `turn-${turnNumber}-source-${number}`;
      sourceIds.set(number, item.id);
    });
  }
  linkCitations(article, panel, sourceIds);
  article.append(panel);
  return article;
}

function linkCitations(article, panel, sourceIds) {
  const walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (/\[\d+\]/.test(node.data) && !node.parentElement.closest("a, code, pre")) {
      nodes.push(node);
    }
  }
  for (const node of nodes) {
    const parts = node.data.split(/(\[\d+\])/);
    node.replaceWith(...parts.map((part, index) => {
      const id = index % 2 === 1 && sourceIds.get(part.slice(1, -1));
      if (!id) return part;
      const link = document.createElement("a");
      link.href = `#${id}`;
      link.textContent = part;
      link.addEventListener("click", () => { panel.open = true; });
      return link;
    }));
  }
}

function openProgress(requestId) {
  if (typeof EventSource === "undefined") return;
  const stream = new EventSource(`/chat/progress/${encodeURIComponent(requestId)}`);
  function receiveProgress(event) {
    try {
      const update = JSON.parse(event.data);
      if (typeof update?.message === "string") progress.textContent = update.message;
    } catch {
      // The chat response can still arrive if a progress update is malformed.
    }
  }
  for (const type of ["agent_started", "tool_finished", "agent_finished"]) {
    stream.addEventListener(type, receiveProgress);
  }
  return stream;
}

async function sendMessage(payload) {
  if (sending) return;
  sending = true;
  retryPayload = null;
  showError("");
  pendingQuestion.textContent = payload.messages.at(-1).content;
  pendingQuestion.hidden = false;
  progress.textContent = "Sending your question…";
  progress.hidden = false;
  updateControls();
  let stream;
  try {
    stream = openProgress(payload.request_id);
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const reply = await response.json();
    if (reply?.request_id !== payload.request_id || typeof reply.answer !== "string"
      || typeof reply.conversation_id !== "string" || !Array.isArray(reply.tool_calls)) {
      throw new Error("Invalid chat response");
    }
    if (!response.ok) {
      if (response.status === 409 && response.headers.has("Retry-After")) {
        retryPayload = payload;
      }
      showError(reply.answer);
      return;
    }

    const question = document.createElement("p");
    question.className = "chat-question";
    question.textContent = pendingQuestion.textContent;
    transcript.append(question, renderAnswer(reply.answer, payload.messages.length));
    messages = [...payload.messages, { role: "assistant", content: reply.answer }];
    conversationId = reply.conversation_id;
    input.value = "";
  } catch {
    retryPayload = payload;
    showError("The connection was interrupted. Retry this message.");
  } finally {
    stream?.close();
    sending = false;
    pendingQuestion.hidden = true;
    progress.hidden = true;
    updateControls();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!content || sending || retryPayload) return;
  void sendMessage({
    conversation_id: conversationId,
    request_id: crypto.randomUUID(),
    messages: [...messages, { role: "user", content }],
  });
});

newChatButton.addEventListener("click", () => {
  messages = [];
  conversationId = null;
  retryPayload = null;
  transcript.replaceChildren();
  input.value = "";
  showError("");
  updateControls();
});

input.addEventListener("input", updateControls);
retryButton.addEventListener("click", () => { void sendMessage(retryPayload); });
checkButton.addEventListener("click", checkConnection);
void checkConnection();
