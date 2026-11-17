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
  ["Finished group topics.", "Sorting the headlines…"],
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
  context.textContent = formatEditionDate(story.last_date);
  button.append(title, context);
  item.append(button);
  return item;
}

async function loadEdition() {
  retryStories.hidden = true;
  storiesStatus.hidden = false;
  storiesStatus.textContent = "Loading recent headlines…";
  try {
    const response = await fetch("/recent-events");
    if (!response.ok) throw new Error("Recent headlines unavailable");
    const edition = await response.json();
    const stories = edition.events.map((story) => renderStory(story, edition));
    const dateLabel = formatEditionDate(edition.end_date);
    storyList.replaceChildren(...stories);
    editionDate.dateTime = edition.end_date;
    editionDate.textContent = dateLabel;
    editionDate.hidden = false;
    storyRule.textContent = "Headlines reported by at least two approved outlets in the past month, ranked by outlet count.";
    storyRule.hidden = false;
    storiesStatus.textContent = stories.length ? "" : "No recent headlines matched this rule.";
    storiesStatus.hidden = stories.length > 0;
    updateControls();
  } catch {
    storiesStatus.textContent = "Recent headlines could not be loaded.";
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
}

function showError(message, toolCalls = []) {
  error.textContent = message;
  error.hidden = !message;
  errorTools.replaceChildren();
  if (toolCalls.length) errorTools.append(renderToolCalls(toolCalls));
}

function formatComparison(table) {
  const headings = Array.from(table.querySelectorAll("thead th"), cell => cell.textContent.trim());
  if (headings.join("|") !== "Aspect|Liberal outlets|Conservative outlets") return;
  table.classList.add("coverage-compare");
  for (const row of table.querySelectorAll("tbody > tr")) {
    Array.from(row.children).forEach((cell, index) => {
      cell.dataset.label = headings[index] ?? "";
      if (index === 0) return;
      const match = cell.textContent.trim().match(/^([●○]{3})\s+(\S+)\s*(?:·\s*)?(.*)$/s);
      if (!match) return;
      const [, dots, label, rest] = match;
      const emphasis = document.createElement("span");
      emphasis.className = `emphasis emphasis-${(dots.match(/●/g) ?? []).length}`;
      const marker = document.createElement("span");
      marker.className = "dots";
      marker.setAttribute("aria-hidden", "true");
      marker.textContent = dots;
      emphasis.append(marker, label);
      const note = document.createElement("span");
      note.className = "coverage-note";
      note.textContent = rest.trim();
      cell.replaceChildren(emphasis, note);
    });
  }
  const legend = table.nextElementSibling;
  if (legend?.matches("p") && legend.textContent.trim().startsWith("●●●")) {
    legend.classList.add("coverage-legend");
  }
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

  const choiceSelector = `a[href^="#${eventChoiceKey}="]`;
  const choiceLists = new Set();
  for (const link of article.querySelectorAll(choiceSelector)) {
    const list = link.closest("li")?.parentElement;
    if (list) choiceLists.add(list);
  }
  for (const list of choiceLists) {
    const choices = document.createElement("ul");
    choices.className = "story-list topic-choices";
    for (const item of list.children) {
      const link = item.querySelector(choiceSelector);
      const params = link && new URLSearchParams(link.getAttribute("href").slice(1));
      const question = params?.get(eventChoiceKey);
      if (!question) continue;
      const title = document.createElement("span");
      title.className = "story-title";
      title.textContent = link.textContent;
      const choice = document.createElement("button");
      choice.type = "button";
      choice.className = "story topic-choice";
      choice.dataset.eventQuestion = question;
      choice.dataset.headline = params.get("headline") ?? "";
      choice.append(title);
      const row = document.createElement("li");
      row.append(choice);
      choices.append(row);
    }
    list.previousElementSibling?.classList.add("topic-prompt");
    list.replaceWith(choices);
  }

  for (const table of article.querySelectorAll("table")) formatComparison(table);

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

async function sendMessage(payload, headline = "", restoreText = null) {
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
  let answered = false;
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
    answered = true;
  } catch {
    retryPayload = payload;
    showError("The connection was interrupted. Retry this message.");
  } finally {
    stream?.close();
    if (!answered && restoreText && retryPayload === null && !input.value) {
      input.value = restoreText;
    }
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
  storyHeadline.hidden = true;
  storyHeadline.textContent = "";
  newspaper.classList.remove("story-view");
}

function submitQuestion(content, headline = "", fromInput = false) {
  if (!connected || !content || sending || retryPayload) return;
  if (startingNewStory) resetConversation();
  draftedHeadline = "";
  const restoreText = fromInput ? input.value : null;
  if (fromInput) input.value = "";
  void sendMessage({
    conversation_id: conversationId,
    request_id: crypto.randomUUID(),
    messages: [...messages, { role: "user", content }],
  }, headline, restoreText);
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const content = input.value.trim();
  const headline = draftedHeadline && content.includes(`“${draftedHeadline}”`) ? draftedHeadline : "";
  submitQuestion(content, headline, true);
});

input.addEventListener("keydown", (event) => {
  const isEnter = event.key === "Enter" || event.keyCode === 13;
  if (!isEnter || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  if (!sendButton.disabled) form.requestSubmit();
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
  if (!storyHeadline.hidden) {
    startingNewStory = true;
    submitQuestion(button.dataset.question, button.dataset.headline);
    return;
  }
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
