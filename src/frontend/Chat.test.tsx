/** Verify chat history and retry behavior at the browser's HTTP boundary. */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Chat from "./Chat";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("retries the same request and includes the clarification in the next turn", async () => {
  const fetchChat = vi.fn()
    .mockRejectedValueOnce(new Error("Connection dropped"))
    .mockImplementation(async (_url: string, init: RequestInit) => {
      const payload = JSON.parse(String(init.body));
      return Response.json({
        conversation_id: "conversation-1",
        request_id: payload.request_id,
        answer: "Which dates should I compare?",
        tool_calls: [],
      });
    });
  vi.stubGlobal("fetch", fetchChat);
  render(<Chat />);

  const input = screen.getByRole("textbox", { name: "Your question" });
  fireEvent.change(input, { target: { value: "Compare earthquake coverage." } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry message" }));
  await screen.findByText("Which dates should I compare?");

  expect(fetchChat.mock.calls[1][1].body).toBe(fetchChat.mock.calls[0][1].body);
  fireEvent.change(input, { target: { value: "November 7–8." } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(fetchChat).toHaveBeenCalledTimes(3));
  expect(JSON.parse(fetchChat.mock.calls[2][1].body)).toMatchObject({
    conversation_id: "conversation-1",
    messages: [
      { role: "user", content: "Compare earthquake coverage." },
      { role: "assistant", content: "Which dates should I compare?" },
      { role: "user", content: "November 7–8." },
    ],
  });
});

it("shows progress from the stream while a request is running", async () => {
  const stream = Object.assign(new EventTarget(), { close: vi.fn() });
  vi.stubGlobal("EventSource", vi.fn(function () { return stream; }));
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
  render(<Chat />);

  fireEvent.change(screen.getByRole("textbox", { name: "Your question" }), {
    target: { value: "Compare the earthquake on November 7." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  act(() => {
    stream.dispatchEvent(new MessageEvent("tool_finished", {
      data: JSON.stringify({ message: "Finished searching the assigned outlets." }),
    }));
  });

  expect(screen.getByRole("status").textContent).toBe("Finished searching the assigned outlets.");
  cleanup();
  expect(stream.close).toHaveBeenCalled();
});
