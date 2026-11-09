/** Exercise the comparison view with the Markdown returned by the agent workflow. */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import ResearchAnswer from "./ResearchAnswer";

afterEach(cleanup);

it("renders the comparison table and lets the reader expand the sources", () => {
  render(<ResearchAnswer answer={`## How the coverage compares
| Aspect | Liberal outlets | Conservative outlets |
| --- | --- | --- |
| Rescue work | Central focus [1] | Central focus [2] |

## Sources
1. NPR [Rescue work continues](https://www.npr.org/story)
2. Fox [Crews assess the damage](https://www.foxnews.com/world/story)

   > Crews assessed the damage before reopening roads.`} />);

  const table = screen.getByRole("table");
  expect(within(table).getByRole("columnheader", { name: "Liberal outlets" })).toBeTruthy();
  expect(within(table).getByRole("cell", { name: "Rescue work" })).toBeTruthy();
  const toggle = screen.getByText("Sources");
  expect(toggle.closest("details")?.open).toBe(false);
  const citation = screen.getByRole("link", { name: "[2]" });
  fireEvent.click(citation);
  expect(toggle.closest("details")?.open).toBe(true);
  expect(screen.getByRole("link", { name: "Rescue work continues" }).getAttribute("href"))
    .toBe("https://www.npr.org/story");
  const destination = document.getElementById(citation.getAttribute("href")?.slice(1) ?? "");
  expect(destination?.textContent).toContain("Crews assessed the damage");
});

it("renders a plain clarification question without an empty sources panel", () => {
  render(<ResearchAnswer answer="Which earthquake and what dates should I compare?" />);

  expect(screen.getByText("Which earthquake and what dates should I compare?")).toBeTruthy();
  expect(screen.queryByText("Sources")).toBeNull();
});
