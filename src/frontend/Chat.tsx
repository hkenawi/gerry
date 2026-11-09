/** Own the current browser conversation and retry one submitted turn safely. */
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import ResearchAnswer from "./ResearchAnswer";

type ChatMessage = { role: "user" | "assistant"; content: string };
type ChatPayload = {
  conversation_id: string | null;
  request_id: string;
  messages: ChatMessage[];
};
type ChatReply = {
  conversation_id: string;
  request_id: string;
  answer: string;
  tool_calls: unknown[];
};

function isChatReply(value: unknown): value is ChatReply {
  return typeof value === "object" && value !== null
    && "conversation_id" in value && typeof value.conversation_id === "string"
    && "request_id" in value && typeof value.request_id === "string"
    && "answer" in value && typeof value.answer === "string"
    && "tool_calls" in value && Array.isArray(value.tool_calls);
}

export default function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [active, setActive] = useState<ChatPayload | null>(null);
  const [retry, setRetry] = useState<ChatPayload | null>(null);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState("");
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => () => inFlight.current?.abort(), []);

  async function send(payload: ChatPayload): Promise<void> {
    if (inFlight.current) return;
    const controller = new AbortController();
    inFlight.current = controller;
    setActive(payload);
    setRetry(null);
    setError("");
    setProgress("");
    let stream: EventSource | undefined;

    function receiveProgress(event: Event): void {
      if (!(event instanceof MessageEvent) || controller.signal.aborted) return;
      try {
        const update: unknown = JSON.parse(event.data);
        if (typeof update === "object" && update !== null
          && "message" in update && typeof update.message === "string") {
          setProgress(update.message);
        }
      } catch {
        // The chat response can still arrive if a progress update is malformed.
      }
    }

    try {
      if (typeof EventSource !== "undefined") {
        stream = new EventSource(`/chat/progress/${encodeURIComponent(payload.request_id)}`);
        controller.signal.addEventListener("abort", () => stream?.close(), { once: true });
        for (const type of ["agent_started", "tool_finished", "agent_finished"]) {
          stream.addEventListener(type, receiveProgress);
        }
      }
      const response = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      const reply: unknown = await response.json();
      if (!isChatReply(reply) || reply.request_id !== payload.request_id) {
        throw new Error("Invalid chat response");
      }
      if (controller.signal.aborted) return;
      if (!response.ok) {
        if (response.status === 409 && response.headers.has("Retry-After")) {
          setRetry(payload);
        }
        setError(reply.answer);
        return;
      }
      setConversationId(reply.conversation_id);
      setMessages([...payload.messages, { role: "assistant", content: reply.answer }]);
      setDraft("");
    } catch {
      if (!controller.signal.aborted) {
        setRetry(payload);
        setError("The connection was interrupted. Retry this message.");
      }
    } finally {
      stream?.close();
      inFlight.current = null;
      if (!controller.signal.aborted) setActive(null);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const content = draft.trim();
    if (!content || retry) return;
    void send({
      conversation_id: conversationId,
      request_id: crypto.randomUUID(),
      messages: [...messages, { role: "user", content }],
    });
  }

  function startNewChat(): void {
    setMessages([]);
    setConversationId(null);
    setDraft("");
    setRetry(null);
    setError("");
  }

  return (
    <section className="chat" aria-label="Gerry chat">
      <div className="chat-heading">
        <h2>Compare coverage</h2>
        {(messages.length > 0 || retry || error) && (
          <button type="button" disabled={active !== null} onClick={startNewChat}>New chat</button>
        )}
      </div>
      {messages.map((message, index) => message.role === "assistant"
        ? <ResearchAnswer key={index} answer={message.content} />
        : <p key={index} className="chat-question">{message.content}</p>)}
      {active && <p className="chat-question">{active.messages.at(-1)?.content}</p>}
      {active && <p role="status">{progress || "Sending your question…"}</p>}
      {error && <p role="alert">{error}</p>}
      {retry && <button type="button" onClick={() => void send(retry)}>Retry message</button>}
      <form className="chat-form" onSubmit={submit}>
        <label htmlFor="gerry-question">Your question</label>
        <textarea
          id="gerry-question"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Name an international event and a date or time period."
          disabled={active !== null || retry !== null}
          rows={3}
        />
        <button type="submit" disabled={!draft.trim() || active !== null || retry !== null}>Send</button>
      </form>
    </section>
  );
}
