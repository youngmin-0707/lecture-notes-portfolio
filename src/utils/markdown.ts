// 요약 본문(detailedNotesMarkdown)을 화면에 그리기 위한 아주 작은 마크다운 렌더러.
// LLM 출력은 app/llm/prompt.py가 "## 헤더 / - 목록 / 1. 목록 / **굵게** / ```코드```"
// 문법만 쓰도록 지시하므로, 그 부분집합만 지원한다 — 범용 마크다운 파서가 아니다.
import { escapeHtml } from "./dom.ts";

const CALLOUT_PREFIX = "💡";

function renderInline(text: string): string {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  return html;
}

type ListKind = "ul" | "ol";

export function renderMarkdown(source: string): string {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const html: string[] = [];

  let listKind: ListKind | null = null;
  let paragraph: string[] = [];
  let inCodeBlock = false;
  let codeLines: string[] = [];

  const closeList = () => {
    if (listKind) {
      html.push(listKind === "ul" ? "</ul>" : "</ol>");
      listKind = null;
    }
  };
  const flushParagraph = () => {
    if (paragraph.length) {
      html.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
      paragraph = [];
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    if (line.trimStart().startsWith("```")) {
      if (inCodeBlock) {
        html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
        inCodeBlock = false;
      } else {
        flushParagraph();
        closeList();
        inCodeBlock = true;
      }
      continue;
    }
    if (inCodeBlock) {
      codeLines.push(rawLine);
      continue;
    }

    const trimmed = line.trim();

    if (trimmed === "") {
      flushParagraph();
      closeList();
      continue;
    }

    const headerMatch = /^(#{2,4})\s+(.*)$/.exec(trimmed);
    if (headerMatch) {
      flushParagraph();
      closeList();
      const level = headerMatch[1].length;
      html.push(`<h${level}>${renderInline(headerMatch[2])}</h${level}>`);
      continue;
    }

    if (trimmed.startsWith(CALLOUT_PREFIX)) {
      flushParagraph();
      closeList();
      html.push(`<div class="notes-callout">${renderInline(trimmed)}</div>`);
      continue;
    }

    const ulMatch = /^[-*]\s+(.*)$/.exec(trimmed);
    const olMatch = /^\d+\.\s+(.*)$/.exec(trimmed);
    if (ulMatch || olMatch) {
      flushParagraph();
      const kind: ListKind = ulMatch ? "ul" : "ol";
      if (listKind !== kind) {
        closeList();
        html.push(kind === "ul" ? "<ul>" : "<ol>");
        listKind = kind;
      }
      html.push(`<li>${renderInline((ulMatch ?? olMatch)![1])}</li>`);
      continue;
    }

    closeList();
    paragraph.push(trimmed);
  }

  flushParagraph();
  closeList();
  if (inCodeBlock) {
    // 닫는 ``` 없이 끝난 경우에도 지금까지 모은 코드는 보여준다.
    html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  }

  return html.join("\n");
}
