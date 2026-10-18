// 세션 상세 화면 (T-33, US-21): 요약/전사 탭 + 오디오 재생·탐색 + 다운로드.
import {
  createQuiz,
  deleteSession,
  exportSession,
  getQuiz,
  getSession,
  getSessionAudioUrl,
  getTranscript,
  updateSession,
  updateSummary,
  type ExportFormat,
  type QuizResponse,
  type SessionDetailResponse,
  type SessionSummaryDetail,
  type TranscriptResponse,
} from "../api/index.ts";
import { getUserErrorMessage } from "../errors/errorMessages.ts";
import { navigate, type RouteParams } from "../router/router.ts";
import { downloadBlob, el, escapeHtml } from "../utils/dom.ts";
import { formatDate, formatDuration, formatTimestamp } from "../utils/format.ts";
import { renderMarkdown } from "../utils/markdown.ts";
import { PROCESSING_STATUSES, STATUS_LABELS } from "../utils/status.ts";
import { renderShell } from "./shell.ts";

const POLL_INTERVAL_MS = 5000;

type Tab = "summary" | "transcript" | "quiz";

// home.ts와 동일한 이유로 세대(generation) 토큰을 쓴다 — 라우터에 unmount 훅이 없어서,
// 다른 페이지로 이동했다가 돌아와도 이전 폴링이 안 멈추는 걸 막는다.
let currentGeneration = 0;
let activeTab: Tab = "summary";
let cachedTranscript: TranscriptResponse | null = null;
let isEditingMeta = false;

// 요약 내용 수정(2026-09-14) 상태. 메타(제목/과목) 편집과 같은 패턴 — 편집 모드 토글은
// 세션 재조회 없이 로컬 상태만 바꾸고, 저장 성공 시 응답으로 받은 최신 세션으로 다시 그린다.
let isEditingSummary = false;
// 세션 삭제(2026-09-14) 진행 중 — 중복 클릭으로 DELETE를 두 번 보내는 것을 막는다.
let isDeletingSession = false;

// 복습 탭(2026-09-01 신규) 상태. `cachedQuiz`가 `null`인 것과 "아직 조회 안 함"을
// 구분해야 해서(전자는 "생성 버튼을 보여줄 시점", 후자는 "일단 조회부터") `quizFetched`를
// 따로 둔다 — 전사 탭의 `cachedTranscript !== null` 단일 체크와 달리, 여기는 null 자체가
// 유효한 "아직 생성 안 됨" 상태이기 때문이다.
let cachedQuiz: QuizResponse | null = null;
let quizFetched = false;
let isCreatingQuiz = false;
let quizActionError: string | null = null;
let revealedQuestions = new Set<number>();

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

/** 2026-08-29 이전에 만들어진 요약(자유형식 본문이 없음)의 개념/코드/과제 섹션. */
function renderLegacySections(summary: SessionSummaryDetail): string {
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

  return `
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
  `;
}

/**
 * 요약 수정 폼(2026-09-14). 메타(제목/과목) 편집(`renderTitleAndMeta`)과 같은 패턴 —
 * "핵심 주제"(keyPoints)는 타임스탬프와 묶여 있어 이 폼으로는 건드리지 않는다(백엔드
 * `PATCH .../summary`도 그 둘만 받는다).
 */
/**
 * 본문 textarea 옆에 실제 렌더링된 모습을 실시간으로 보여주는 미리보기 패널(2026-09-14).
 * 완전한 인라인(WYSIWYG) 편집 대신 이 방식을 택한 이유: 저장되는 값은 항상 순수 마크다운
 * 문자열(`detailedNotesMarkdown`)이고 내보내기(MD/TXT)·`content_markdown` 재조립도 그
 * 마크다운을 그대로 쓴다 — contenteditable로 렌더링된 HTML을 직접 고치게 하면 저장할 때
 * 다시 마크다운으로 역변환해야 하는데, 그 과정에서 제목·목록 구조가 꼬이거나 손상될 위험이
 * 있다. 기존에 검증된 `renderMarkdown()`을 입력할 때마다 그대로 재사용해 "타이핑하는
 * 그대로 어떻게 보일지"를 안전하게 보여준다.
 */
function updateSummaryEditPreview(): void {
  const notesInput = el<"textarea">("summary-edit-notes");
  const preview = el<"div">("summary-edit-preview");
  if (!notesInput || !preview) return;
  const text = notesInput.value.trim();
  preview.innerHTML = text
    ? renderMarkdown(text)
    : `<p class="empty-state">본문을 입력하면 여기에 미리보기가 보입니다.</p>`;
}

function renderSummaryEditForm(summary: SessionSummaryDetail): string {
  const detailedNotes = summary.detailedNotesMarkdown ?? "";
  return `
    <form id="summary-edit-form" class="summary-edit-form">
      <label for="summary-edit-one-line">한 줄 요약</label>
      <input
        type="text"
        id="summary-edit-one-line"
        value="${escapeHtml(extractOneLineSummary(summary.contentMarkdown))}"
        maxlength="500"
      />
      <label for="summary-edit-notes">본문</label>
      <div class="summary-edit-split">
        <textarea id="summary-edit-notes" rows="18">${escapeHtml(detailedNotes)}</textarea>
        <div id="summary-edit-preview" class="notes-body summary-edit-preview">
          ${detailedNotes.trim() ? renderMarkdown(detailedNotes) : `<p class="empty-state">본문을 입력하면 여기에 미리보기가 보입니다.</p>`}
        </div>
      </div>
      <div id="summary-edit-status"></div>
      <div class="summary-edit-actions">
        <button type="submit" class="btn btn--export">저장</button>
        <button type="button" id="summary-edit-cancel" class="btn btn--export">취소</button>
      </div>
    </form>
  `;
}

function renderSummaryTab(session: SessionDetailResponse): string {
  const summary = session.summary;
  if (!summary) {
    return `<p class="empty-state">아직 요약이 없습니다.</p>`;
  }

  if (isEditingSummary) {
    return renderSummaryEditForm(summary);
  }

  const editButtonHtml = PROCESSING_STATUSES.includes(session.status)
    ? ""
    : `<button type="button" id="summary-edit-start" class="edit-icon-btn" aria-label="요약 내용 수정">✎ 수정</button>`;

  const keyPointsHtml = summary.keyPoints.length
    ? `<ul class="key-point-list">${summary.keyPoints
        .map((kp) => {
          // 텍스트 파일로 만든 세션에는 시간축이 없어 atSeconds가 null이다 — 이동할 지점이
          // 없으므로 "[00:00]" 버튼 대신 항목만 보여준다 (2026-09-14).
          const jumpButton =
            kp.atSeconds === null
              ? ""
              : `<button type="button" class="timestamp-link" data-jump="${kp.atSeconds}">[${formatTimestamp(kp.atSeconds)}]</button>`;
          return `
            <li>
              ${jumpButton}
              ${escapeHtml(kp.text)}
            </li>
          `;
        })
        .join("")}</ul>`
    : `<p>없음</p>`;

  // "복습 키워드" 섹션은 사용률이 낮아 2026-09-01부로 제거했다 — 앞으로 생성되는 요약은
  // keywords가 항상 빈 배열이라 이 섹션이 자연스럽게 안 보인다. 이미 keywords가 채워진
  // 과거 요약(2026-09-01 이전 생성)은 그대로 계속 보여준다(데이터를 지우거나 문서를
  // 소급 수정하지 않는다).
  const keywordsHtml = summary.keywords.length
    ? `
      <section class="summary-section">
        <h3>복습 키워드</h3>
        <p>${escapeHtml(summary.keywords.join(", "))}</p>
      </section>
    `
    : "";

  // 자유형식 본문이 있으면 그걸 주 콘텐츠로 렌더링하고, 없는(2026-08-29 이전) 요약은
  // 예전 개념/코드/과제 구조화 섹션으로 폴백한다. HMR로 갱신된 페이지가 API 응답 갱신 전
  // 필드를 잠깐 놓칠 수도 있어(구버전 캐시 등) undefined도 방어적으로 다룬다.
  const detailedNotes = summary.detailedNotesMarkdown ?? "";
  const bodyHtml = detailedNotes.trim()
    ? `
      <section class="summary-section">
        <div class="notes-body">${renderMarkdown(detailedNotes)}</div>
      </section>
    `
    : renderLegacySections(summary);

  return `
    <div class="summary-content">
      <div class="summary-content__toolbar">${editButtonHtml}</div>
      <section class="summary-section">
        <h3>한 줄 요약</h3>
        <p>${escapeHtml(extractOneLineSummary(summary.contentMarkdown))}</p>
      </section>
      <section class="summary-section">
        <h3>핵심 주제</h3>
        ${keyPointsHtml}
      </section>
      ${bodyHtml}
      ${keywordsHtml}
    </div>
  `;
}

function renderTranscriptTab(transcript: TranscriptResponse | null): string {
  if (!transcript) {
    return `<p class="empty-state">아직 전사가 없습니다.</p>`;
  }
  if (transcript.segments.length === 0) {
    // 타임스탬프가 없는 전사(텍스트 파일 업로드, 2026-09-14)는 본문을 그대로 보여준다 —
    // 세그먼트가 없다는 이유로 내용 전체를 숨기면 텍스트 세션에서는 볼 게 아무것도 없다.
    if (transcript.text.trim()) {
      return `<p class="transcript-plain">${escapeHtml(transcript.text)}</p>`;
    }
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

function renderQuizTab(quiz: QuizResponse | null): string {
  const statusHtml = quizActionError
    ? `<p class="status status--error">${escapeHtml(quizActionError)}</p>`
    : "";

  if (!quiz) {
    return `
      ${statusHtml}
      <div class="quiz-empty">
        <p class="empty-state">아직 복습 문제가 없습니다.</p>
        <button type="button" id="quiz-generate-button" class="btn btn--export" ${isCreatingQuiz ? "disabled" : ""}>
          ${isCreatingQuiz ? "생성 중..." : "복습 문제 만들기"}
        </button>
      </div>
    `;
  }

  if (quiz.status === "GENERATING") {
    return `${statusHtml}<p class="status status--loading">복습 문제를 만드는 중입니다...</p>`;
  }

  if (quiz.status === "FAILED") {
    return `
      ${statusHtml}
      <div class="quiz-empty">
        <p class="status status--error">복습 문제 생성에 실패했습니다: ${escapeHtml(quiz.errorMessage ?? "")}</p>
        <button type="button" id="quiz-generate-button" class="btn btn--export" ${isCreatingQuiz ? "disabled" : ""}>
          ${isCreatingQuiz ? "생성 중..." : "다시 생성"}
        </button>
      </div>
    `;
  }

  if (quiz.questions.length === 0) {
    return `${statusHtml}<p class="empty-state">생성된 문제가 없습니다.</p>`;
  }

  const itemsHtml = quiz.questions
    .map((q, i) => {
      const revealed = revealedQuestions.has(i);
      return `
        <li class="quiz-item">
          <p class="quiz-item__question">Q${i + 1}. ${escapeHtml(q.question)}</p>
          ${
            revealed
              ? `<p class="quiz-item__answer">${escapeHtml(q.answer)}</p>`
              : `<button type="button" class="btn btn--export" data-quiz-reveal="${i}">정답 보기</button>`
          }
        </li>
      `;
    })
    .join("");

  return `
    ${statusHtml}
    <ul class="quiz-list">${itemsHtml}</ul>
    <button type="button" id="quiz-generate-button" class="btn btn--export" ${isCreatingQuiz ? "disabled" : ""}>
      ${isCreatingQuiz ? "생성 중..." : "복습 문제 다시 생성"}
    </button>
  `;
}

function renderTabContent(session: SessionDetailResponse): void {
  const target = el("tab-content");
  if (!target) return;
  if (activeTab === "summary") {
    target.innerHTML = renderSummaryTab(session);
  } else if (activeTab === "transcript") {
    target.innerHTML = renderTranscriptTab(cachedTranscript);
  } else {
    target.innerHTML = renderQuizTab(cachedQuiz);
  }
}

function updateTabButtons(): void {
  const summaryBtn = el<"button">("tab-summary");
  const transcriptBtn = el<"button">("tab-transcript");
  const quizBtn = el<"button">("tab-quiz");
  summaryBtn?.classList.toggle("tab-button--active", activeTab === "summary");
  transcriptBtn?.classList.toggle("tab-button--active", activeTab === "transcript");
  quizBtn?.classList.toggle("tab-button--active", activeTab === "quiz");
}

function setExportStatus(html: string): void {
  const target = el("export-status");
  if (target) target.innerHTML = html;
}

async function handleExport(sessionId: string, format: ExportFormat): Promise<void> {
  setExportStatus(`<p class="status status--loading">내보내는 중...</p>`);
  try {
    const result = await exportSession(sessionId, format);
    downloadBlob(result.blob, result.filename);
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
        void Promise.all([
          loadTranscriptIfNeeded(sessionId, generation),
          loadQuizIfNeeded(sessionId, generation),
        ]).then(() => {
          if (generation !== currentGeneration) return;
          // renderTabContent는 아래에서 세션 재조회 없이도 캐시된 정보로 다시 그린다.
          const cachedSession = lastRenderedSession;
          if (cachedSession) renderTabContent(cachedSession);
        });
      }
      return;
    }

    const revealButton = target.closest<HTMLButtonElement>("[data-quiz-reveal]");
    if (revealButton) {
      const index = Number.parseInt(revealButton.dataset.quizReveal ?? "-1", 10);
      if (index >= 0) {
        revealedQuestions.add(index);
        if (lastRenderedSession) renderTabContent(lastRenderedSession);
      }
      return;
    }

    if (target.closest("#quiz-generate-button")) {
      void handleCreateQuiz(sessionId, generation);
      return;
    }

    const exportButton = target.closest<HTMLButtonElement>("[data-export]");
    if (exportButton) {
      const format = exportButton.dataset.export as ExportFormat | undefined;
      if (format) void handleExport(sessionId, format);
      return;
    }

    if (target.closest("#meta-edit-start")) {
      isEditingMeta = true;
      if (lastRenderedSession) rerenderMetaArea(lastRenderedSession);
      return;
    }

    if (target.closest("#meta-edit-cancel")) {
      isEditingMeta = false;
      if (lastRenderedSession) rerenderMetaArea(lastRenderedSession);
      return;
    }

    if (target.closest("#summary-edit-start")) {
      isEditingSummary = true;
      if (lastRenderedSession) renderTabContent(lastRenderedSession);
      return;
    }

    if (target.closest("#summary-edit-cancel")) {
      isEditingSummary = false;
      if (lastRenderedSession) renderTabContent(lastRenderedSession);
      return;
    }

    if (target.closest("#session-delete-button")) {
      void handleDeleteSession(sessionId, generation);
    }
  });

  container.addEventListener("submit", (event) => {
    const form = event.target as HTMLElement;
    if (form.id === "meta-edit-form") {
      event.preventDefault();
      void handleMetaEditSubmit(sessionId, generation);
    }
    if (form.id === "summary-edit-form") {
      event.preventDefault();
      void handleSummaryEditSubmit(sessionId, generation);
    }
  });

  // 본문 textarea에 입력할 때마다 옆 미리보기를 즉시 갱신한다 (2026-09-14).
  container.addEventListener("input", (event) => {
    if ((event.target as HTMLElement).id === "summary-edit-notes") {
      updateSummaryEditPreview();
    }
  });
}

async function handleMetaEditSubmit(sessionId: string, generation: number): Promise<void> {
  const titleInput = el<"input">("meta-edit-title");
  const courseInput = el<"input">("meta-edit-course");
  const title = titleInput?.value.trim() ?? "";
  const course = courseInput?.value.trim() ?? "";

  if (!title) {
    setMetaEditStatus(`<p class="status status--error">제목은 비워둘 수 없습니다.</p>`);
    return;
  }

  try {
    const updated = await updateSession(sessionId, { title, course: course || undefined });
    if (generation !== currentGeneration) return;
    lastRenderedSession = updated;
    isEditingMeta = false;
    setMetaEditStatus("");
    rerenderMetaArea(updated);
  } catch (error) {
    setMetaEditStatus(`<p class="status status--error">${getUserErrorMessage(error)}</p>`);
  }
}

function setMetaEditStatus(html: string): void {
  const target = el("meta-edit-status");
  if (target) target.innerHTML = html;
}

function rerenderMetaArea(session: SessionDetailResponse): void {
  const target = el("session-meta-area");
  if (target) target.innerHTML = renderTitleAndMeta(session);
}

async function handleSummaryEditSubmit(sessionId: string, generation: number): Promise<void> {
  const oneLineInput = el<"input">("summary-edit-one-line");
  const notesInput = el<"textarea">("summary-edit-notes");
  const oneLineSummary = oneLineInput?.value.trim() ?? "";
  const detailedNotesMarkdown = notesInput?.value.trim() ?? "";

  if (!oneLineSummary || !detailedNotesMarkdown) {
    setSummaryEditStatus(
      `<p class="status status--error">한 줄 요약과 본문은 비워둘 수 없습니다.</p>`,
    );
    return;
  }

  try {
    const updated = await updateSummary(sessionId, { oneLineSummary, detailedNotesMarkdown });
    if (generation !== currentGeneration) return;
    lastRenderedSession = updated;
    isEditingSummary = false;
    renderTabContent(updated);
  } catch (error) {
    if (generation !== currentGeneration) return;
    setSummaryEditStatus(`<p class="status status--error">${getUserErrorMessage(error)}</p>`);
  }
}

function setSummaryEditStatus(html: string): void {
  const target = el("summary-edit-status");
  if (target) target.innerHTML = html;
}

/**
 * 세션 삭제(2026-09-14, US-18 백엔드 `DELETE /sessions/{id}`를 화면에 연결). 오디오·전사·
 * 요약·복습 문제가 모두 함께 지워지는 되돌릴 수 없는 동작이라 네이티브 confirm으로 한 번 더
 * 확인한다. 성공하면 더 이상 존재하지 않는 세션 상세 화면에 머물 수 없으므로 홈으로 이동한다.
 */
async function handleDeleteSession(sessionId: string, generation: number): Promise<void> {
  if (isDeletingSession) return;
  const confirmed = window.confirm(
    "정말 이 세션을 삭제하시겠습니까?\n오디오·전사·요약·복습 문제가 모두 함께 삭제되며 되돌릴 수 없습니다.",
  );
  if (!confirmed) return;

  isDeletingSession = true;
  const button = el<"button">("session-delete-button");
  if (button) {
    button.disabled = true;
    button.textContent = "삭제하는 중...";
  }
  setDeleteStatus("");

  try {
    await deleteSession(sessionId);
    if (generation !== currentGeneration) return;
    navigate("#/");
  } catch (error) {
    if (generation !== currentGeneration) return;
    isDeletingSession = false;
    if (button) {
      button.disabled = false;
      button.textContent = "세션 삭제";
    }
    setDeleteStatus(`<p class="status status--error">${getUserErrorMessage(error)}</p>`);
  }
}

function setDeleteStatus(html: string): void {
  const target = el("session-delete-status");
  if (target) target.innerHTML = html;
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

/** 복습 탭을 처음 열 때 딱 한 번 조회한다 — `QUIZ_NOT_FOUND`(아직 생성 안 함)도 정상
 * 흐름이라 `cachedQuiz = null`로만 남기고 계속 진행한다. */
async function loadQuizIfNeeded(sessionId: string, generation: number): Promise<void> {
  if (activeTab !== "quiz" || quizFetched) return;
  await refreshQuiz(sessionId, generation);
}

async function refreshQuiz(sessionId: string, generation: number): Promise<void> {
  try {
    const quiz = await getQuiz(sessionId);
    if (generation !== currentGeneration) return;
    cachedQuiz = quiz;
  } catch {
    if (generation !== currentGeneration) return;
    cachedQuiz = null;
  }
  if (generation !== currentGeneration) return;
  quizFetched = true;
  if (cachedQuiz?.status === "GENERATING") {
    scheduleQuizPoll(sessionId, generation);
  }
}

function scheduleQuizPoll(sessionId: string, generation: number): void {
  window.setTimeout(() => {
    void pollQuizOnce(sessionId, generation);
  }, POLL_INTERVAL_MS);
}

async function pollQuizOnce(sessionId: string, generation: number): Promise<void> {
  if (generation !== currentGeneration) return;
  try {
    const quiz = await getQuiz(sessionId);
    if (generation !== currentGeneration) return;
    cachedQuiz = quiz;
  } catch {
    if (generation !== currentGeneration) return;
    cachedQuiz = null;
  }
  if (generation !== currentGeneration) return;
  if (activeTab === "quiz") renderTabContent(lastRenderedSession as SessionDetailResponse);
  if (cachedQuiz?.status === "GENERATING") {
    scheduleQuizPoll(sessionId, generation);
  }
}

async function handleCreateQuiz(sessionId: string, generation: number): Promise<void> {
  if (isCreatingQuiz) return;
  isCreatingQuiz = true;
  quizActionError = null;
  revealedQuestions = new Set();
  if (activeTab === "quiz" && lastRenderedSession) renderTabContent(lastRenderedSession);

  try {
    await createQuiz(sessionId);
    if (generation !== currentGeneration) return;
    await refreshQuiz(sessionId, generation);
  } catch (error) {
    if (generation !== currentGeneration) return;
    quizActionError = getUserErrorMessage(error);
  } finally {
    if (generation === currentGeneration) isCreatingQuiz = false;
  }
  if (generation !== currentGeneration) return;
  if (activeTab === "quiz" && lastRenderedSession) renderTabContent(lastRenderedSession);
}

function renderTitleAndMeta(session: SessionDetailResponse): string {
  if (isEditingMeta) {
    return `
      <form id="meta-edit-form" class="meta-edit-form">
        <input type="text" id="meta-edit-title" value="${escapeHtml(session.title)}" maxlength="200" placeholder="제목" />
        <input type="text" id="meta-edit-course" value="${escapeHtml(session.course ?? "")}" maxlength="100" placeholder="과목 (선택)" />
        <button type="submit" class="btn btn--export">저장</button>
        <button type="button" id="meta-edit-cancel" class="btn btn--export">취소</button>
      </form>
    `;
  }

  const metaParts = [
    session.course,
    formatDuration(session.durationSeconds),
    formatDate(session.recordedAt),
  ].filter((part): part is string => Boolean(part));

  return `
    <h1>${escapeHtml(session.title)} <button type="button" id="meta-edit-start" class="edit-icon-btn" aria-label="제목·과목 수정">✎</button></h1>
    <p class="session-detail__meta">
      <span class="badge badge--${session.status.toLowerCase()}">${STATUS_LABELS[session.status]}</span>
      ${escapeHtml(metaParts.join(" · "))}
    </p>
  `;
}

function renderSessionShell(session: SessionDetailResponse): string {
  // 요약까지 끝나면 원본 오디오를 지우므로(2026-08-29), 없을 땐 빈 플레이어 대신 안내만
  // 보여준다. 텍스트 파일로 만든 세션(2026-09-14)은 애초에 오디오가 없으니 이유도 다르게 쓴다.
  const audioSection = session.audioAvailable
    ? `<audio id="audio-player" controls preload="none" src="${getSessionAudioUrl(session.sessionId)}"></audio>`
    : session.source === "TEXT"
      ? `<p class="audio-unavailable-notice">텍스트 파일로 등록한 세션이라 오디오가 없습니다.</p>`
      : `<p class="audio-unavailable-notice">오디오 원본은 요약 완료 후 자동으로 삭제됩니다. 아래 텍스트로 확인해주세요.</p>`;

  const processingNotice = PROCESSING_STATUSES.includes(session.status)
    ? `<p class="status status--loading">처리 중입니다... 자동으로 갱신됩니다.</p>`
    : "";
  const failedNotice =
    session.status === "FAILED"
      ? `<p class="status status--error">처리 실패: ${escapeHtml(session.errorMessage ?? "")}</p>`
      : "";

  return `
    <a href="#/" class="back-link">← 홈으로</a>
    <div id="session-meta-area">${renderTitleAndMeta(session)}</div>
    <div id="meta-edit-status"></div>
    ${processingNotice}
    ${failedNotice}

    ${audioSection}

    <div class="tabs">
      <button type="button" id="tab-summary" class="tab-button" data-tab="summary">요약</button>
      <button type="button" id="tab-transcript" class="tab-button" data-tab="transcript">전사</button>
      <button type="button" id="tab-quiz" class="tab-button" data-tab="quiz">복습</button>
    </div>

    <div class="export-buttons">
      <button type="button" class="btn btn--export" data-export="md">MD 다운로드</button>
      <button type="button" class="btn btn--export" data-export="txt">TXT 다운로드</button>
      ${
        // SRT는 세그먼트 자막 포맷이라 시간축이 없는 텍스트 세션에서는 빈 파일이 나온다
        // — 받을 수 있는 것처럼 보여주지 않는다 (2026-09-14).
        session.source === "TEXT"
          ? ""
          : `<button type="button" class="btn btn--export" data-export="srt">SRT 다운로드</button>`
      }
    </div>
    <div id="export-status"></div>

    <div id="tab-content"></div>

    <div class="danger-zone">
      <button
        type="button"
        id="session-delete-button"
        class="btn btn--delete"
        ${PROCESSING_STATUSES.includes(session.status) ? "disabled" : ""}
      >
        세션 삭제
      </button>
      <div id="session-delete-status"></div>
    </div>
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

  await Promise.all([
    loadTranscriptIfNeeded(sessionId, generation),
    loadQuizIfNeeded(sessionId, generation),
  ]);
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
  isEditingMeta = false;
  isEditingSummary = false;
  isDeletingSession = false;
  cachedQuiz = null;
  quizFetched = false;
  isCreatingQuiz = false;
  quizActionError = null;
  revealedQuestions = new Set();

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
