/** Render a cited answer or clarification using the workflow's Markdown contract. */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useId, useRef } from "react";

const sourceHeading = "\n## Sources\n";

export default function ResearchAnswer({ answer }: { answer: string }) {
  const sourceId = useId();
  const sourcePanel = useRef<HTMLDetailsElement>(null);
  const sourceIndex = answer.lastIndexOf(sourceHeading);
  const briefing = sourceIndex < 0 ? answer : answer.slice(0, sourceIndex);
  const sources = sourceIndex < 0 ? "" : answer.slice(sourceIndex + sourceHeading.length).trim();
  const sourceLines = sources.split("\n");
  const sourceNumbers = new Set(Array.from(sources.matchAll(/^(\d+)\. /gm), (match) => match[1]));
  const linkedBriefing = briefing.replace(/(?<!\[)\[(\d+)\](?![\[(])/g, (marker, number: string) =>
    sourceNumbers.has(number) ? `[\\[${number}\\]](#${sourceId}-source-${number})` : marker,
  );

  return (
    <article className="research-answer" aria-label="Research answer">
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} onClick={() => {
              if (href?.startsWith(`#${sourceId}-source-`) && sourcePanel.current) {
                sourcePanel.current.open = true;
              }
            }}>{children}</a>
          ),
          table: ({ children }) => (
            <div className="comparison-scroll" role="region" aria-label="Coverage comparison" tabIndex={0}>
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {linkedBriefing}
      </ReactMarkdown>
      {sources && (
        <details className="research-sources" ref={sourcePanel}>
          <summary>Sources</summary>
          <ReactMarkdown skipHtml components={{
            li: ({ children, node }) => {
              const line = node?.position?.start.line ?? 0;
              const number = sourceLines[line - 1]?.match(/^(\d+)\. /)?.[1];
              return <li id={number ? `${sourceId}-source-${number}` : undefined}>{children}</li>;
            },
          }}>{sources}</ReactMarkdown>
        </details>
      )}
    </article>
  );
}
