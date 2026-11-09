/** Render a cited answer or clarification using the workflow's Markdown contract. */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const sourceHeading = "\n## Sources\n";

export default function ResearchAnswer({ answer }: { answer: string }) {
  const sourceIndex = answer.lastIndexOf(sourceHeading);
  const briefing = sourceIndex < 0 ? answer : answer.slice(0, sourceIndex);
  const sources = sourceIndex < 0 ? "" : answer.slice(sourceIndex + sourceHeading.length).trim();

  return (
    <article className="research-answer" aria-label="Research answer">
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children }) => (
            <div className="comparison-scroll" role="region" aria-label="Coverage comparison" tabIndex={0}>
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {briefing}
      </ReactMarkdown>
      {sources && (
        <details className="research-sources">
          <summary>Sources</summary>
          <ReactMarkdown skipHtml>{sources}</ReactMarkdown>
        </details>
      )}
    </article>
  );
}
