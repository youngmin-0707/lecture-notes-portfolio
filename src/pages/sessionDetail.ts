// 세션 상세 화면 (T-33, US-21): 요약/전사 탭 + 오디오 재생·탐색 + 다운로드.
import {
  exportSession,
  getSession,
  getSessionAudioUrl,
  getTranscript,
  type ExportFormat,
  type SessionDetailResponse,
  type SessionSummaryDetail,
  type TranscriptResponse,
} from "../api/index.ts";
import { getUserErrorMessage } from "../errors/errorMessages.ts";
import type { RouteParams } from "../router/router.ts";
import { el, escapeHtml } from "../utils/dom.ts";
import { renderShell } from "./shell.ts";

const PROCESSING_STATUSES = ["TRANSCRIBING", "SUMMARIZING"];
const POLL_INTERVAL_MS = 5000;

type Tab = "summary" | "transcript";

// home.ts와 동일한 이유로 세대(generation) 토큰을 쓴다 — 라우터에 unmount 훅이 없어서,
// 다른 페이지로 이동했다가 돌아와도 이전 폴링이 안 멈추는 걸 막는다.
let currentGeneration = 0;
let activeTab: Tab = "summary";
let cachedTranscript: TranscriptResponse | null = null;

function formatTimestamp(seconds: number): string {
  const total = Math.max(Math.floor(seconds), 0);
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  return formatTimestamp(seconds);
}

function formatDate(iso: string | undefined): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("ko-KR", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/**
 * `contentMarkdown`의 "## 한 줄 요약" 섹션만 뽑는다 — 백엔드(app/api/v1/sessions.py의
 * `_extract_summary_preview`)와 동일한 접근이다. `SessionSummaryDetail`에 별도
 * `oneLineSummary` 필드가 없고 렌더링된 마크다운 전체(`contentMarkdown`)만 있어서,
 * 나머지 구조화 필드(keyPoints 등)처럼 이것만 따로 마크다운에서 뽑아낸다.
 */
function extractOneLineSummary(contentMarkdown: string): string {
  const marker = "## 한 줄 요약\n";
  const start = contentMarkdown.indexOf(marker);
  if (start === -1) return contentMarkdown.trim();
  const rest = contentMarkdown.slice(start + marker.length);
  const end = rest.indexOf("\n##");
  return (end === -1 ? rest : rest.slice(0, end)).trim();
}

function jumpToAudio(seconds: number): void {
  const audio = el<"audio">("audio-player");
  if (!audio) return;
  audio.currentTime = seconds;
  void audio.play().catch(() => {
    // 자동재생 정책 등으로 play()가 거부될 수 있다 — currentTime 이동 자체는 이미 됐으므로
    // 사용자가 재생 버튼을 누르면 그 지점부터 재생된다. 조용히 무시한다.
  });
}

function renderSummaryTab(summary: SessionSummaryDetail | null): string {
  if (!summary) {
    return `<p class="empty-state">아직 요약이 없습니다.</p>`;
  }

  const keyPointsHtml = summary.keyPoints.length
    ? `<ul class="key-point-list">${summary.keyPoints
        .map(
          (kp) => `
            <li>
              <button type="button" class="timestamp-link" data-jump="${kp.atSeconds}">[${formatTimestamp(kp.atSeconds)}]</button>
              ${escapeHtml(kp.text)}
            </li>
          `,
        )
        .join("")}</ul>`
    : `<p>없음</p>`;

  const conceptsHtml = summary.concepts.length
    ? `<ul>${summary.concepts
        .map((c) => `<li><strong>${escapeHtml(c.term)}</strong>: ${escapeHtml(c.description)}</li>`)
        .join("")}</ul>`
    : `<p>없음</p>`;

  const codeHtml = summary.codeSnippets.length
    ? summary.codeSnippets
        .map(
          (snippet) => `
            <div class="code-snippet">
              <pre><code>${escapeHtml(snippet.code)}</code></pre>
              ${snippet.description ? `<p class="code-snippet__desc">${escapeHtml(snippet.description)}</p>` : ""}
            </div>
          `,
        )
        .join("")
    : `<p>없음</p>`;

  const actionHtml = summary.actionItems.length
    ? `<ul>${summary.actionItems
        .map(
          (item) =>
            `<li>${escapeHtml(item.text)}${item.dueDate ? ` (마감: ${escapeHtml(item.dueDate)})` : ""}</li>`,
        )
        .join("")}</ul>`
    : `<p>없음</p>`;

  const keywordsText = summary.keywords.length ? summary.keywords.join(", ") : "없음";

  return `
    <div class="summary-content">
      <section class="summary-section">
        <h3>한 줄 요약</h3>
        <p>${escapeHtml(extractOneLineSummary(summary.contentMarkdown))}</p>
      </section>
      <section class="summary-section">
        <h3>핵심 주제</h3>
        ${keyPointsHtml}
      </section>
      <section class="summary-section">
        <h3>개념 정리</h3>
        ${conceptsHtml}
      </section>
      <section class="summary-section">
        <h3>코드 / 명령어</h3>
        ${codeHtml}
      </section>
      <section class="summary-section">
        <h3>과제 및 공지</h3>
        ${actionHtml}
      </section>
      <section class="summary-section">
        <h3>복습 키워드</h3>
        <p>${escapeHtml(keywordsText)}</p>
      </section>
    </div>
  `;
}

function renderTranscriptTab(transcript: TranscriptResponse | null): string {
  if (!transcript) {
    return `<p class="empty-state">아직 전사가 없습니다.</p>`;
  }
  if (transcript.segments.length === 0) {
    return `<p class="empty-state">전사 세그먼트가 없습니다.</p>`;
  }
  return `
    <ul class="segment-list">
      ${transcript.segments
        .map(
          (segment) => `
            <li>
              <button type="button" class="timestamp-link" data-jump="${segment.startSeconds}">[${formatTimestamp(segment.startSeconds)}]</button>
              <span>${escapeHtml(segment.text)}</span>
            </li>
          `,
        )
        .join("")}
    </ul>
  `;
}

function renderTabContent(session: SessionDetailResponse): void {
  const target = el("tab-content");
  if (!target) return;
  target.innerHTML =
    activeTab === "summary"
      ? renderSummaryTab(session.summary)
      : renderTranscriptTab(cachedTranscript);
}

function updateTabButtons(): void {
  const summaryBtn = el<"button">("tab-summary");
  const transcriptBtn = el<"button">("tab-transcript");
  summaryBtn?.classList.toggle("tab-button--active", activeTab === "summary");
  transcriptBtn?.classList.toggle("tab-button--active", activeTab === "transcript");
}

function setExportStatus(html: string): void {
  const target = el("export-status");
  if (target) target.innerHTML = html;
}

async function handleExport(sessionId: string, format: ExportFormat): Promise<void> {
  setExportStatus(`<p class="status status--loading">내보내는 중...</p>`);
  try {
    const result = await exportSession(sessionId, format);
    const url = URL.createObjectURL(result.blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = result.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setExportStatus("");
  } catch (error) {
    setExportStatus(`<p class="status status--error">${getUserErrorMessage(error)}</p>`);
  }
}

function wireInteractions(sessionId: string, generation: number): void {
  const container = el("session-detail-page");
  if (!container) return;

  container.addEventListener("click", (event) => {
    if (generation !== currentGeneration) return;
    const target = event.target as HTMLElement;

    const jumpButton = target.closest<HTMLButtonElement>("[data-jump]");
    if (jumpButton) {
      const seconds = Number.parseFloat(jumpButton.dataset.jump ?? "0");
      if (!Number.isNaN(seconds)) jumpToAudio(seconds);
      return;
    }

    const tabButton = target.closest<HTMLButtonElement>("[data-tab]");
    if (tabButton) {
      const tab = tabButton.dataset.tab as Tab | undefined;
      if (tab && tab !== activeTab) {
        activeTab = tab;
        updateTabButtons();
        void loadTranscriptIfNeeded(sessionId, generation).then(() => {
          if (generation !== currentGeneration) return;
          // renderTabContent는 아래에서 세션 재조회 없이도 캐시된 정보로 다시 그린다.
          const cachedSession = lastRenderedSession;
          if (cachedSession) renderTabContent(cachedSession);
        });
      }
      return;
    }

    const exportButton = target.closest<HTMLButtonElement>("[data-export]");
    if (exportButton) {
      const format = exportButton.dataset.export as ExportFormat | undefined;
      if (format) void handleExport(sessionId, format);
    }
  });
}

let lastRenderedSession: SessionDetailResponse | null = null;

async function loadTranscriptIfNeeded(sessionId: string, generation: number): Promise<void> {
  if (activeTab !== "transcript" || cachedTranscript !== null) return;
  try {
    const transcript = await getTranscript(sessionId);
    if (generation !== currentGeneration) return;
    cachedTranscript = transcript;
  } catch {
    // 전사가 아직 준비 안 됐거나(409) 등 — 탭 렌더링 쪽에서 "아직 전사가 없습니다"로 보여준다.
  }
}

function renderStatusBadgeLabel(status: string): string {
  const labels: Record<string, string> = {
    UPLOADED: "업로드됨",
    TRANSCRIBING: "전사 중",
    TRANSCRIBED: "전사 완료",
    SUMMARIZING: "요약 중",
    DONE: "완료",
    FAILED: "실패",
  };
  return labels[status] ?? status;
}

function renderSessionShell(session: SessionDetailResponse): string {
  const audioUrl = getSessionAudioUrl(session.sessionId);
  const metaParts = [
    session.course,
    formatDuration(session.durationSeconds),
    formatDate(session.recordedAt),
  ].filter((part): part is string => Boolean(part));

  const processingNotice = PROCESSING_STATUSES.includes(session.status)
    ? `<p class="status status--loading">처리 중입니다... 자동으로 갱신됩니다.</p>`
    : "";
  const failedNotice =
    session.status === "FAILED"
      ? `<p class="status status--error">처리 실패: ${escapeHtml(session.errorMessage ?? "")}</p>`
      : "";

  return `
    <a href="#/" class="back-link">← 홈으로</a>
    <h1>${escapeHtml(session.title)}</h1>
    <p class="session-detail__meta">
      <span class="badge badge--${session.status.toLowerCase()}">${renderStatusBadgeLabel(session.status)}</span>
      ${escapeHtml(metaParts.join(" · "))}
    </p>
    ${processingNotice}
    ${failedNotice}

    <audio id="audio-player" controls preload="none" src="${audioUrl}"></audio>

    <div class="tabs">
      <button type="button" id="tab-summary" class="tab-button" data-tab="summary">요약</button>
      <button type="button" id="tab-transcript" class="tab-button" data-tab="transcript">전사</button>
    </div>

    <div class="export-buttons">
      <button type="button" class="btn btn--export" data-export="md">MD 다운로드</button>
      <button type="button" class="btn btn--export" data-export="txt">TXT 다운로드</button>
      <button type="button" class="btn btn--export" data-export="srt">SRT 다운로드</button>
    </div>
    <div id="export-status"></div>

    <div id="tab-content"></div>
  `;
}

async function loadAndRender(sessionId: string, generation: number): Promise<void> {
  let session: SessionDetailResponse;
  try {
    session = await getSession(sessionId);
  } catch (error) {
    if (generation !== currentGeneration) return;
    renderShell(
      "home",
      `
        <section class="placeholder">
          <h1>세션을 불러올 수 없습니다</h1>
          <p class="status status--error">${getUserErrorMessage(error)}</p>
          <a href="#/">← 홈으로</a>
        </section>
      `,
    );
    return;
  }

  if (generation !== currentGeneration) return;
  lastRenderedSession = session;

  renderShell("home", `<section id="session-detail-page">${renderSessionShell(session)}</section>`);
  updateTabButtons();
  wireInteractions(sessionId, generation);

  await loadTranscriptIfNeeded(sessionId, generation);
  if (generation !== currentGeneration) return;
  renderTabContent(session);

  if (PROCESSING_STATUSES.includes(session.status)) {
    window.setTimeout(() => {
      if (generation !== currentGeneration) return;
      cachedTranscript = null; // 처리 완료 후 다시 받아오도록 캐시를 비운다.
      void loadAndRender(sessionId, generation);
    }, POLL_INTERVAL_MS);
  }
}

export function renderSessionDetailPage(params: RouteParams): void {
  const generation = ++currentGeneration;
  activeTab = "summary";
  cachedTranscript = null;
  lastRenderedSession = null;

  const sessionId = params.id;
  if (!sessionId) {
    renderShell(
      "home",
      `<section class="placeholder"><h1>잘못된 경로입니다</h1><a href="#/">← 홈으로</a></section>`,
    );
    return;
  }

  renderShell(
    "home",
    `<section><p class="status status--loading">불러오는 중...</p></section>`,
  );
  void loadAndRender(sessionId, generation);
}
