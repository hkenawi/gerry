/** Present Gerry's purpose and verify the backend without invoking research. */
import { useEffect, useState } from "react";

type ConnectionState = "checking" | "ready" | "unavailable";

export default function App() {
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setConnection("checking");

    async function checkConnection(): Promise<void> {
      try {
        const response = await fetch("/health", { signal: controller.signal });
        const body: unknown = await response.json();
        const healthy = response.ok && typeof body === "object" && body !== null
          && "status" in body && body.status === "ok";
        if (!controller.signal.aborted) {
          setConnection(healthy ? "ready" : "unavailable");
        }
      } catch {
        if (!controller.signal.aborted) setConnection("unavailable");
      }
    }

    void checkConnection();
    return () => controller.abort();
  }, [attempt]);

  return (
    <main>
      <header className="masthead">
        <a className="wordmark" href="/" aria-label="Gerry home">gerry<span>.</span></a>
        <span className="edition">More perspectives. Better context.</span>
      </header>

      <section className="introduction" aria-labelledby="purpose">
        <p className="eyebrow">News, with room for perspective</p>
        <h1 id="purpose">A wider view of the same story.</h1>
        <p className="description">
          Compare how selected liberal and conservative news outlets cover an
          international event. See what they emphasize, where they overlap, and
          the sources behind the comparison.
        </p>
      </section>

      <section className="connection-panel" aria-label="Gerry availability">
        <p role="status" aria-live="polite">
          <span className={`status-dot ${connection}`} aria-hidden="true" />
          {connection === "checking" && "Connecting to Gerry…"}
          {connection === "ready" && "Connected to Gerry"}
          {connection === "unavailable" && "Can't connect to Gerry right now."}
        </p>
        {connection === "unavailable" ? (
          <button type="button" onClick={() => setAttempt((value) => value + 1)}>
            Try again
          </button>
        ) : <p className="availability-note">Research will be available here soon.</p>}
      </section>

      <footer>A comparison of sampled reporting, with attribution and context.</footer>
    </main>
  );
}
