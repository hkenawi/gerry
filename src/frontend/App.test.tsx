/** Exercise the browser shell at its visible UI and network boundary. */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("explains Gerry and confirms the backend connection", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ status: "ok" }),
  }));
  render(<App />);

  expect(screen.getByRole("heading", { name: "A wider view of the same story." })).toBeTruthy();
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Connected to Gerry"));
});

it("shows a useful retry action when the backend cannot be reached", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Connection refused")));
  render(<App />);

  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Can't connect"));
  expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
});
