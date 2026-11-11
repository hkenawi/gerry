import MarkdownIt from "./markdown-it-15.0.3.mjs";

const markdown = new MarkdownIt({ html: false, linkify: true });
const eventChoiceKey = "compare-event";
const newspaper = document.getElementById("newspaper");
const storyHeadline = document.getElementById("story-headline");
const transcript = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("gerry-question");
const sendButton = document.getElementById("send-message");
const retryButton = document.getElementById("retry-message");
const newChatButton = document.getElementById("new-chat");
const investigateButton = document.getElementById("investigate-further");
const pendingQuestion = document.getElementById("pending-question");
const progress = document.getElementById("progress");
const error = document.getElementById("error");
const errorTools = document.getElementById("error-tools");
const checkButton = document.getElementById("check-connection");
const connectionMessage = document.getElementById("connection-message");
const editionDate = document.getElementById("edition-date");
const storyList = document.getElementById("story-list");
const storiesStatus = document.getElementById("stories-status");
const storyRule = document.getElementById("story-rule");
const retryStories = document.getElementById("retry-stories");
const dateFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
});
const openingProgress = "Mandering…";
const toolProgress = new Map([
  ["Finished search recent events.", "Polling the headlines…"],
  ["Finished search articles.", "Drawing political lines…"],
  ["Finished read article.", "Entering evidence into the record…"],
  ["Finished read collected article.", "Reopening the record…"],
  ["Finished research liberal coverage.", "Finding bipartisanship…"],
  ["Finished research conservative coverage.", "Finding bipartisanship…"],
  ["Finished write answer.", "Solving disputes…"],
]);

let messages = [];
let conversationId = null;
let retryPayload = null;
let sending = false;
let connected = false;
let startingNewStory = false;
let draftedHeadline = "";

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

function formatEditionDate(date) {
  return dateFormatter.format(new Date(date));
}

function renderStory(story, edition) {
  const item = document.createElement("li");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "story";
  button.dataset.headline = story.headline;
  button.dataset.question = `How did different outlets cover “${story.headline}” from ${edition.start_date} to ${edition.end_date}?`;
  const title = document.createElement("span");
  title.className = "story-title";
  title.textContent = story.headline;
  const context = document.createElement("span");
  context.className = "story-context";
  context.textContent = `${story.headline_outlet} · ${formatEditionDate(story.last_date)}`;
  if (story.snippet) context.textContent += ` — ${story.snippet}`;
  button.append(title, context);
  item.append(button);
  return item;
}

async function loadEdition() {
  retryStories.hidden = true;
  storiesStatus.hidden = false;
  storiesStatus.textContent = "Loading recent stories…";
  try {
    const response = await fetch("/recent-events");
    if (!response.ok) throw new Error("Recent stories unavailable");
    const edition = await response.json();
    const stories = edition.events.map((story) => renderStory(story, edition));
    const dateLabel = formatEditionDate(edition.end_date);
    storyList.replaceChildren(...stories);
    editionDate.dateTime = edition.end_date;
    editionDate.textContent = dateLabel;
    editionDate.hidden = false;
    storyRule.textContent = "Stories reported by at least two approved outlets in the past month, ranked by outlet count.";
    storyRule.hidden = false;
    storiesStatus.textContent = stories.length ? "" : "No recent stories matched this rule.";
    storiesStatus.hidden = stories.length > 0;
    updateControls();
  } catch {
    storiesStatus.textContent = "Recent stories could not be loaded.";
    retryStories.hidden = false;
  }
}

function updateControls() {
  input.disabled = sending || retryPayload !== null;
  sendButton.disabled = !connected || input.disabled || !input.value.trim();
  for (const button of storyList.querySelectorAll("button[data-question]")) {
    button.disabled = input.disabled;
  }
  for (const button of transcript.querySelectorAll("button[data-event-question]")) {
    button.disabled = !connected || input.disabled;
  }
  retryButton.hidden = retryPayload === null;
  newChatButton.hidden = storyHeadline.hidden;
  newChatButton.disabled = sending;
  investigateButton.disabled = !connected || input.disabled || startingNewStory;
}

function showError(message, toolCalls = []) {
  error.textContent = message;
  error.hidden = !message;
  errorTools.replaceChildren();
  if (toolCalls.length) errorTools.append(renderToolCalls(toolCalls));
}

function hasCoverageToInvestigate(toolCalls) {
  return toolCalls.some(({ tool, outcome, result }) => {
    if (outcome !== "success") return false;
    if (tool === "read_article") return true;
    if (tool !== "write_answer") return false;
    try {
      return ["comparison", "summary_only"].includes(JSON.parse(result)?.mode);
    } catch {
      return false;
    }
  });
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

  for (const link of article.querySelectorAll(`a[href^="#${eventChoiceKey}="]`)) {
    const params = new URLSearchParams(link.getAttribute("href").slice(1));
    const question = params.get(eventChoiceKey);
    if (!question) continue;
    const choice = document.createElement("button");
    choice.type = "button";
    choice.className = "secondary-button";
    choice.dataset.eventQuestion = question;
    choice.dataset.headline = params.get("headline") ?? "";
    choice.textContent = link.textContent;
    link.replaceWith(choice);
  }

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
      if (value == null) {
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
      if (typeof update?.message !== "string") return;
      const message = event.type === "tool_finished"
        ? toolProgress.get(update.message) ?? (
          update.message.startsWith("Could not complete ")
            ? "Hitting a procedural snag…"
            : "Keeping the debate going…"
        )
        : event.type === "agent_finished" ? "Closing arguments…" : openingProgress;
      if (progress.textContent !== message) progress.textContent = message;
    } catch {
      // The chat response can still arrive if a progress update is malformed.
    }
  }
  for (const type of ["agent_started", "tool_finished", "agent_finished"]) {
    stream.addEventListener(type, receiveProgress);
  }
  return stream;
}

async function sendMessage(payload, headline = "") {
  if (sending) return;
  sending = true;
  retryPayload = null;
  showError("");
  pendingQuestion.textContent = payload.messages.at(-1).content;
  pendingQuestion.hidden = messages.length === 0;
  if (storyHeadline.hidden) {
    storyHeadline.textContent = headline || pendingQuestion.textContent;
    storyHeadline.hidden = false;
    newspaper.classList.add("story-view");
    storyHeadline.focus();
  }
  progress.textContent = openingProgress;
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
    if (answer.querySelector(".research-sources") || hasCoverageToInvestigate(reply.tool_calls)) {
      investigateButton.hidden = false;
    }
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
  draftedHeadline = "";
  transcript.replaceChildren();
  investigateButton.hidden = true;
  storyHeadline.hidden = true;
  storyHeadline.textContent = "";
  newspaper.classList.remove("story-view");
}

function submitQuestion(content, headline = "") {
  if (!connected || !content || sending || retryPayload) return;
  if (startingNewStory) resetConversation();
  draftedHeadline = "";
  void sendMessage({
    conversation_id: conversationId,
    request_id: crypto.randomUUID(),
    messages: [...messages, { role: "user", content }],
  }, headline);
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const content = input.value.trim();
  const headline = draftedHeadline && content.includes(`“${draftedHeadline}”`) ? draftedHeadline : "";
  submitQuestion(content, headline);
});

investigateButton.addEventListener("click", () => {
  if (investigateButton.hidden || investigateButton.disabled) return;
  submitQuestion("Go deeper on the previous briefing. What else did the reporting uncover, and what’s still unclear?");
});

newChatButton.addEventListener("click", () => {
  resetConversation();
  input.value = "";
  showError("");
  updateControls();
  input.focus();
});

input.addEventListener("input", updateControls);
storyList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-question]");
  if (!button || button.disabled) return;
  startingNewStory = !storyHeadline.hidden;
  draftedHeadline = button.dataset.headline;
  input.value = button.dataset.question;
  updateControls();
  input.focus();
});
transcript.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-event-question]");
  if (!button || button.disabled) return;
  startingNewStory = true;
  submitQuestion(button.dataset.eventQuestion, button.dataset.headline);
});
retryButton.addEventListener("click", () => { void sendMessage(retryPayload); });
checkButton.addEventListener("click", checkConnection);
retryStories.addEventListener("click", loadEdition);
void checkConnection();
void loadEdition();
