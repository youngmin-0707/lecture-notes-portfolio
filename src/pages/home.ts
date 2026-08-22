// 메인 화면 (T-31, US-20): 드래그앤드롭 업로드 + 최근 세션 목록 + 폴링.
import {
  createSessionWithProgress,
  getHealth,
  listSessions,
  processSession,
  type SessionListItem,
  type UploadProgressEvent,
} from "../api/index.ts";
import { getUserErrorMessage } from "../errors/errorMessages.ts";
import { el, escapeHtml } from "../utils/dom.ts";
import { formatDate, formatDuration } from "../utils/format.ts";
import { PROCESSING_STATUSES, STATUS_LABELS } from "../utils/status.ts";
import { renderShell } from "./shell.ts";

// §3.1 업로드 검증 규칙과 동일한 허용 형식/용량. 서버가 매직 넘버로 최종 판정하므로
// 이건 어디까지나 "업로드 전에 걸러서 UX를 개선"하는 1차 필터일 뿐이다.
const ALLOWED_EXTENSIONS = ["mp3", "m4a", "wav", "webm", "ogg", "flac", "mp4", "mpeg"];
const MAX_UPLOAD_SIZE_BYTES = 500 * 1024 * 1024;

const POLL_INTERVAL_MS = 5000;

// 라우터에 명시적 unmount 훅이 없어서(T-30 스켈레톤), 페이지를 벗어났다가 다시 들어와도
// 이전 폴링 루프가 계속 도는 걸 막기 위해 "이 렌더가 아직 최신인가"를 세대(generation)로
// 판별한다. renderHomePage()가 다시 호출될 때마다 세대가 올라가고, 오래된 세대의 폴링은
// 스스로 멈춘다.
let currentGeneration = 0;
let isUploading = false;
const retryingIds = new Set<string>();

// --- T-32: 브라우저 녹음(MediaRecorder) 상태 ---
let mediaRecorder: MediaRecorder | null = null;
let recordedChunks: Blob[] = [];
let recordingStartedAt: number | null = null;
let recordingTimerId: number | null = null;

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

// MediaRecorder가 실제로 사용한 mimeType에서 업로드 파일 확장자를 정한다 — 백엔드는
// 매직 넘버로 최종 검증하지만(§3.1), 클라이언트 1차 필터(validateFileClientSide)를 통과하려면
// 파일명 확장자가 §3.1 허용 목록에 든 것이어야 한다.
function extensionFromMimeType(mimeType: string): string {
  if (mimeType.includes("mp4")) return "mp4";
  if (mimeType.includes("ogg")) return "ogg";
  if (mimeType.includes("wav")) return "wav";
  return "webm"; // 대부분의 브라우저(Chrome/Firefox) 기본값.
}

function validateFileClientSide(file: File): string | null {
  const ext = file.name.includes(".") ? (file.name.split(".").pop() ?? "").toLowerCase() : "";
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    return `지원하지 않는 파일 형식입니다${ext ? ` (.${ext})` : ""}. 지원 형식: ${ALLOWED_EXTENSIONS.join(", ")}`;
  }
  if (file.size > MAX_UPLOAD_SIZE_BYTES) {
    const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
    return `파일 크기가 최대 500MB를 초과합니다 (현재 ${sizeMb}MB).`;
  }
  return null;
}

function renderSessionCard(session: SessionListItem): string {
  const isProcessing = PROCESSING_STATUSES.includes(session.status);
  const badgeClass = `badge badge--${session.status.toLowerCase()}`;
  const preview = session.summaryPreview
    ? `<p class="session-card__preview">${escapeHtml(session.summaryPreview)}</p>`
    : "";
  const retryButton =
    session.status === "FAILED"
      ? `<button type="button" class="btn btn--retry" data-retry-id="${session.sessionId}" ${
          retryingIds.has(session.sessionId) ? "disabled" : ""
        }>${retryingIds.has(session.sessionId) ? "재시도 중..." : "다시 시도"}</button>`
      : "";
  const processingHint = isProcessing
    ? `<p class="session-card__hint">자동으로 상태를 갱신하는 중...</p>`
    : "";

  return `
    <li class="session-card" data-session-id="${session.sessionId}">
      <div class="session-card__main">
        <span class="${badgeClass}">${STATUS_LABELS[session.status]}</span>
        <a class="session-card__title" href="#/sessions/${encodeURIComponent(session.sessionId)}">
          ${escapeHtml(session.title)}
        </a>
        <span class="session-card__meta">
          ${session.course ? escapeHtml(session.course) + " · " : ""}${formatDuration(session.durationSeconds)} ·
          ${formatDate(session.recordedAt)}
        </span>
      </div>
      ${preview}
      ${processingHint}
      ${retryButton}
    </li>
  `;
}

function renderSessionList(sessions: SessionListItem[]): void {
  const target = el("session-list");
  if (!target) return;
  if (sessions.length === 0) {
    target.innerHTML = `<p class="empty-state">아직 업로드한 강의가 없습니다.</p>`;
    return;
  }
  target.innerHTML = `<ul class="session-list">${sessions.map(renderSessionCard).join("")}</ul>`;
}

function setUploadStatus(html: string): void {
  const target = el("upload-status");
  if (target) target.innerHTML = html;
}

function setDropzoneBusy(busy: boolean): void {
  const dropzone = el<"div">("dropzone");
  const input = el<"input">("file-input");
  if (dropzone) dropzone.classList.toggle("dropzone--busy", busy);
  if (input) input.disabled = busy;
}

async function refreshSessions(generation: number): Promise<SessionListItem[]> {
  try {
    const result = await listSessions({ size: 20 });
    if (generation !== currentGeneration) return result.items;
    renderSessionList(result.items);
    return result.items;
  } catch (error) {
    if (generation !== currentGeneration) return [];
    const target = el("session-list");
    if (target) {
      target.innerHTML = `<p class="status status--error">${getUserErrorMessage(error)}</p>`;
    }
    return [];
  }
}

function schedulePoll(generation: number): void {
  if (generation !== currentGeneration) return;
  window.setTimeout(() => {
    void pollOnce(generation);
  }, POLL_INTERVAL_MS);
}

async function pollOnce(generation: number): Promise<void> {
  if (generation !== currentGeneration) return;
  const items = await refreshSessions(generation);
  if (generation !== currentGeneration) return;
  if (items.some((item) => PROCESSING_STATUSES.includes(item.status))) {
    schedulePoll(generation);
  }
}

function maybeStartPolling(generation: number, items: SessionListItem[]): void {
  if (items.some((item) => PROCESSING_STATUSES.includes(item.status))) {
    schedulePoll(generation);
  }
}

async function handleRetry(sessionId: string, generation: number): Promise<void> {
  if (retryingIds.has(sessionId)) return;
  retryingIds.add(sessionId);
  const items = await refreshSessions(generation);
  renderSessionList(items);
  try {
    await processSession(sessionId);
    retryingIds.delete(sessionId);
    const refreshed = await refreshSessions(generation);
    maybeStartPolling(generation, refreshed);
  } catch (error) {
    retryingIds.delete(sessionId);
    setUploadStatus(`<p class="status status--error">재시도 실패: ${getUserErrorMessage(error)}</p>`);
    void refreshSessions(generation);
  }
}

async function handleFile(file: File, generation: number): Promise<void> {
  if (isUploading || mediaRecorder) return; // 중복 제출 차단 (US-20) + 녹음 중 업로드 방지.

  const validationError = validateFileClientSide(file);
  if (validationError) {
    setUploadStatus(`<p class="status status--error">${validationError}</p>`);
    return;
  }

  isUploading = true;
  setDropzoneBusy(true);
  setUploadStatus(`
    <div class="upload-progress">
      <div class="upload-progress__bar" id="upload-progress-bar" style="width: 0%"></div>
    </div>
    <p class="status status--loading" id="upload-progress-text">업로드 중... 0%</p>
  `);

  try {
    const result = await createSessionWithProgress({ file, autoProcess: true }, (progress) => {
      if (generation !== currentGeneration) return;
      updateUploadProgress(progress);
    });
    if (generation !== currentGeneration) return;
    setUploadStatus(
      `<p class="status status--ok">업로드 완료: ${escapeHtml(result.title)} (처리를 시작했습니다)</p>`,
    );
    const items = await refreshSessions(generation);
    maybeStartPolling(generation, items);
  } catch (error) {
    if (generation !== currentGeneration) return;
    setUploadStatus(`<p class="status status--error">${getUserErrorMessage(error)}</p>`);
  } finally {
    isUploading = false;
    setDropzoneBusy(false);
  }
}

function updateUploadProgress(progress: UploadProgressEvent): void {
  const bar = el<"div">("upload-progress-bar");
  const text = el<"p">("upload-progress-text");
  if (bar) bar.style.width = `${progress.percent}%`;
  if (text) text.textContent = `업로드 중... ${progress.percent}%`;
}

function setRecordStatus(html: string): void {
  const target = el("record-status");
  if (target) target.innerHTML = html;
}

function updateRecordButtonUi(recording: boolean): void {
  const button = el<"button">("record-toggle");
  const timer = el<"span">("record-timer");
  if (button) {
    button.textContent = recording ? "⏹ 녹음 종료" : "🎙 녹음 시작";
    button.classList.toggle("btn--recording", recording);
  }
  if (timer) timer.hidden = !recording;
  setDropzoneBusy(recording); // 녹음 중에는 파일 업로드도 막아 상태가 꼬이지 않게 한다.
}

function stopRecordTimer(): void {
  if (recordingTimerId !== null) {
    window.clearInterval(recordingTimerId);
    recordingTimerId = null;
  }
}

function startRecordTimer(generation: number): void {
  stopRecordTimer();
  recordingTimerId = window.setInterval(() => {
    if (generation !== currentGeneration || recordingStartedAt === null) {
      stopRecordTimer();
      return;
    }
    const timer = el<"span">("record-timer");
    if (timer) timer.textContent = formatElapsed(Date.now() - recordingStartedAt);
  }, 1000);
}

async function startRecording(generation: number): Promise<void> {
  if (mediaRecorder || isUploading) return; // 이미 녹음 중이거나 업로드 중이면 무시.

  if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    setRecordStatus(
      `<p class="status status--error">이 브라우저는 녹음 기능을 지원하지 않습니다.</p>`,
    );
    return;
  }

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    // US-19: 마이크 권한 거부 시 정확히 이 문구를 보여준다.
    const isPermissionDenied =
      error instanceof DOMException &&
      (error.name === "NotAllowedError" || error.name === "PermissionDeniedError");
    setRecordStatus(
      `<p class="status status--error">${
        isPermissionDenied ? "마이크 권한이 필요합니다." : "마이크에 접근할 수 없습니다."
      }</p>`,
    );
    return;
  }

  if (generation !== currentGeneration) {
    stream.getTracks().forEach((track) => track.stop());
    return;
  }

  recordedChunks = [];
  const recorder = new MediaRecorder(stream);
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0) recordedChunks.push(event.data);
  });
  recorder.addEventListener("stop", () => {
    stream.getTracks().forEach((track) => track.stop());
  });

  recorder.start();
  mediaRecorder = recorder;
  recordingStartedAt = Date.now();
  setRecordStatus("");
  updateRecordButtonUi(true);
  startRecordTimer(generation);
}

function stopRecording(generation: number): void {
  if (!mediaRecorder) return;
  const recorder = mediaRecorder;
  const mimeType = recorder.mimeType || "audio/webm";
  mediaRecorder = null;
  stopRecordTimer();
  recordingStartedAt = null;
  updateRecordButtonUi(false);

  recorder.addEventListener(
    "stop",
    () => {
      void finishRecording(mimeType, generation);
    },
    { once: true },
  );
  recorder.stop();
}

async function finishRecording(mimeType: string, generation: number): Promise<void> {
  const blob = new Blob(recordedChunks, { type: mimeType });
  recordedChunks = [];
  if (blob.size === 0) {
    setRecordStatus(`<p class="status status--error">녹음된 내용이 없습니다.</p>`);
    return;
  }
  const extension = extensionFromMimeType(mimeType);
  const file = new File([blob], `recording-${Date.now()}.${extension}`, { type: mimeType });
  await handleFile(file, generation); // 검증·업로드·목록갱신·폴링을 그대로 재사용한다.
}

function wireRecorder(generation: number): void {
  const button = el<"button">("record-toggle");
  if (!button) return;
  button.addEventListener("click", () => {
    if (mediaRecorder) {
      stopRecording(generation);
    } else {
      void startRecording(generation);
    }
  });
}

function wireDropzone(generation: number): void {
  const dropzone = el<"div">("dropzone");
  const input = el<"input">("file-input");
  if (!dropzone || !input) return;

  dropzone.addEventListener("click", () => {
    if (!isUploading) input.click();
  });

  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    if (!isUploading) dropzone.classList.add("dropzone--dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dropzone--dragover");
  });

  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("dropzone--dragover");
    const file = event.dataTransfer?.files?.[0];
    if (file) void handleFile(file, generation);
  });

  input.addEventListener("change", () => {
    const file = input.files?.[0];
    if (file) void handleFile(file, generation);
    input.value = ""; // 같은 파일을 다시 골라도 change 이벤트가 나가도록 초기화.
  });
}

function wireRetryButtons(generation: number): void {
  const list = el<"div">("session-list");
  if (!list) return;
  list.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    const button = target.closest<HTMLButtonElement>("[data-retry-id]");
    if (!button) return;
    const sessionId = button.dataset.retryId;
    if (sessionId) void handleRetry(sessionId, generation);
  });
}

function renderHealthWidget(): void {
  const target = el<"div">("health-status");
  if (!target) return;
  getHealth()
    .then((health) => {
      const badgeClass = health.status === "ok" ? "status--ok" : "status--degraded";
      target.innerHTML = `
        <p class="status ${badgeClass}">
          서버 상태: <strong>${health.status}</strong>
          (STT: ${health.checks.stt.provider ?? "-"} / LLM: ${health.checks.llm.provider ?? "-"} /
          오프라인 모드: ${health.checks.offlineMode ? "예" : "아니오"})
        </p>
      `;
    })
    .catch((error: unknown) => {
      target.innerHTML = `<p class="status status--error">${getUserErrorMessage(error)}</p>`;
    });
}

export function renderHomePage(): void {
  const generation = ++currentGeneration;
  isUploading = false;
  retryingIds.clear();
  if (mediaRecorder) {
    mediaRecorder.stream.getTracks().forEach((track) => track.stop());
    mediaRecorder = null;
  }
  stopRecordTimer();
  recordingStartedAt = null;
  recordedChunks = [];

  renderShell(
    "home",
    `
      <section>
        <h1>강의 녹음 업로드</h1>
        <div id="dropzone" class="dropzone" role="button" tabindex="0">
          <p>오디오 파일을 여기로 드래그하거나 클릭해서 선택하세요</p>
          <p class="dropzone__hint">지원 형식: ${ALLOWED_EXTENSIONS.join(", ")} · 최대 500MB</p>
          <input type="file" id="file-input" accept="audio/*" hidden />
        </div>
        <div id="upload-status"></div>
        <div class="recorder">
          <button type="button" id="record-toggle" class="btn btn--record">🎙 녹음 시작</button>
          <span id="record-timer" class="record-timer" hidden>00:00</span>
        </div>
        <div id="record-status"></div>
      </section>
      <section>
        <h2>최근 세션</h2>
        <div id="session-list"><p class="status status--loading">불러오는 중...</p></div>
      </section>
      <div id="health-status"></div>
    `,
  );

  wireDropzone(generation);
  wireRecorder(generation);
  wireRetryButtons(generation);
  renderHealthWidget();

  void refreshSessions(generation).then((items) => {
    maybeStartPolling(generation, items);
  });
}
