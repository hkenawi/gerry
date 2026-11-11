import MarkdownIt from "./markdown-it-15.0.3.mjs";

const markdown = new MarkdownIt({ html: false, linkify: true });
const newspaper = document.getElementById("newspaper");
const storyHeadline = document.getElementById("story-headline");
const transcript = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("gerry-question");
const sendButton = document.getElementById("send-message");
const retryButton = document.getElementById("retry-message");
const newChatButton = document.getElementById("new-chat");
const pendingQuestion = document.getElementById("pending-question");
const progress = document.getElementById("progress");
const error = document.getElementById("error");
const errorTools = document.getElementById("error-tools");
const checkButton = document.getElementById("check-connection");
const connectionMessage = document.getElementById("connection-message");
const storyButtons = document.querySelectorAll("button[data-question]");

let messages = [];
let conversationId = null;
let retryPayload = null;
let sending = false;
let connected = false;
let startingNewStory = false;

async function checkConnection() {
  checkButton.hidden = true;
  connectionMessage.textContent = "";
  try {
    const response = await fetch("/health");
    connected = response.ok && (await response.json())?.status === "ok";
  } catch {
    // A failed health check leaves the retry button available.
  }
  connectionMessage.textContent = connected ? "" : "Can't connect to Gerry right now.";
  checkButton.hidden = connected;
  updateControls();
}

function updateControls() {
  input.disabled = sending || retryPayload !== null;
  sendButton.disabled = !connected || input.disabled || !input.value.trim();
  for (const button of storyButtons) {
    button.disabled = input.disabled;
  }
  retryButton.hidden = retryPayload === null;
  newChatButton.hidden = storyHeadline.hidden;
  newChatButton.disabled = sending;
}

function showError(message, toolCalls = []) {
  error.textContent = message;
  error.hidden = !message;
  errorTools.replaceChildren();
  if (toolCalls.length) errorTools.append(renderToolCalls(toolCalls));
}

function formatCoverageColumns(table) {
  const header = table.querySelector("thead tr");
  const headings = Array.from(header?.children ?? [], cell => cell.textContent.trim());
  const bodies = table.querySelectorAll("tbody");
  const rows = Array.from(table.querySelectorAll("tbody > tr"));
  if (headings.join("|") !== "Aspect|Liberal outlets|Conservative outlets"
    || !rows.length || rows.some(row => row.children.length !== 3)) return;

  header.firstElementChild.remove();
  for (const heading of header.children) heading.setAttribute("scope", "col");

  for (const row of rows) {
    const aspect = row.firstElementChild;
    const heading = document.createElement("th");
    heading.setAttribute("scope", "rowgroup");
    heading.setAttribute("colspan", "2");
    heading.append(...aspect.childNodes);
    aspect.remove();

    const headingRow = document.createElement("tr");
    headingRow.append(heading);
    const group = document.createElement("tbody");
    group.append(headingRow, row);
    table.append(group);
  }

  for (const body of bodies) body.remove();
  table.classList.add("coverage-columns");
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
    formatCoverageColumns(table);
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

function renderToolCalls(toolCalls) {
  const panel = document.createElement("details");
  panel.className = "research-tools";
  const summary = document.createElement("summary");
  summary.textContent = `Tools used (${toolCalls.length})`;
  const list = document.createElement("ol");

  for (const call of toolCalls) {
    const item = document.createElement("li");
    const inspector = document.createElement("details");
    inspector.className = "tool-inspector";
    const callSummary = document.createElement("summary");
    const name = document.createElement("code");
    name.textContent = call.tool;
    const metadata = document.createElement("span");
    const outcome = call.outcome === "success" ? "Succeeded" : "Failed";
    metadata.textContent = ` · ${call.agent} · ${outcome}`;
    callSummary.append(name, metadata);
    inspector.append(callSummary);

    if (call.error) {
      const reason = document.createElement("p");
      reason.textContent = call.error;
      inspector.append(reason);
    }

    const payloads = document.createElement("dl");
    for (const [label, value] of [["Arguments", call.args], ["Return value", call.result]]) {
      const term = document.createElement("dt");
      term.textContent = label;
      const description = document.createElement("dd");
      if (value === undefined) {
        description.textContent = "Unavailable";
      } else {
        const payload = document.createElement("pre");
        payload.tabIndex = 0;
        payload.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
        description.append(payload);
      }
      payloads.append(term, description);
    }
    inspector.append(payloads);
    item.append(inspector);
    list.append(item);
  }

  panel.append(summary, list);
  return panel;
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
  pendingQuestion.hidden = messages.length === 0;
  if (storyHeadline.hidden) {
    storyHeadline.textContent = pendingQuestion.textContent;
    storyHeadline.hidden = false;
    newspaper.classList.add("story-view");
    storyHeadline.focus();
  }
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
      showError(reply.answer, reply.tool_calls);
      return;
    }

    if (messages.length) {
      const question = document.createElement("p");
      question.className = "chat-question";
      question.textContent = pendingQuestion.textContent;
      transcript.append(question);
    }
    const answer = renderAnswer(reply.answer, payload.messages.length);
    if (reply.tool_calls.length) answer.append(renderToolCalls(reply.tool_calls));
    transcript.append(answer);
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

function resetConversation() {
  messages = [];
  conversationId = null;
  retryPayload = null;
  startingNewStory = false;
  transcript.replaceChildren();
  storyHeadline.hidden = true;
  storyHeadline.textContent = "";
  newspaper.classList.remove("story-view");
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!connected || !content || sending || retryPayload) return;
  if (startingNewStory) resetConversation();
  void sendMessage({
    conversation_id: conversationId,
    request_id: crypto.randomUUID(),
    messages: [...messages, { role: "user", content }],
  });
});

newChatButton.addEventListener("click", () => {
  resetConversation();
  input.value = "";
  showError("");
  updateControls();
  input.focus();
});

input.addEventListener("input", updateControls);
for (const button of storyButtons) {
  button.addEventListener("click", () => {
    startingNewStory = !storyHeadline.hidden;
    input.value = button.dataset.question;
    updateControls();
    input.focus();
  });
}
retryButton.addEventListener("click", () => { void sendMessage(retryPayload); });
checkButton.addEventListener("click", checkConnection);
void checkConnection();
