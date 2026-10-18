// 요구사항 문서 §5 API 설계와 1:1 대응하는 타입 정의.
// (docs/requirements/stt-transcription.md §5.3 참고)

export type SessionStatus =
  | "UPLOADED"
  | "TRANSCRIBING"
  | "TRANSCRIBED"
  | "SUMMARIZING"
  | "DONE"
  | "FAILED";

/** 2026-09-14: 오디오 대신 텍스트 파일(.txt/.md)을 올린 세션은 "TEXT"다. */
export type SessionSource = "UPLOAD" | "RECORD" | "TEXT";

export type ProgressStage = "TRANSCRIBING" | "SUMMARIZING";

export type MatchedIn = "TRANSCRIPT" | "SUMMARY";

export type ExportFormat = "md" | "txt" | "srt";

/** §5.1 공통 에러 응답 포맷 */
export interface ApiErrorDetail {
  field: string;
  reason: string;
  message: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: ApiErrorDetail[];
  };
  requestId: string;
}

/** ① POST /sessions 응답 */
export interface CreateSessionResponse {
  sessionId: string;
  title: string;
  course: string | null;
  status: SessionStatus;
  source: SessionSource;
  originalFilename: string;
  fileSizeBytes: number;
  /** 텍스트 파일 업로드에는 재생 길이가 없다(null). */
  durationSeconds: number | null;
  recordedAt: string;
  createdAt: string;
  pollAfterSeconds?: number;
}

export interface CreateSessionParams {
  file: File;
  title?: string;
  course?: string;
  autoProcess?: boolean;
}

/** ② POST /sessions/{id}/process 요청/응답 */
export interface ProcessSessionRequest {
  sttModel?: string;
  llmProvider?: string;
  skipSummary?: boolean;
}

export interface ProcessSessionResponse {
  sessionId: string;
  status: SessionStatus;
  pollAfterSeconds: number;
}

/** ③ GET /sessions/{id} 응답 */
export interface SessionProgress {
  stage: ProgressStage;
  percent: number;
  etaSeconds: number | null;
}

export interface SessionTranscriptInfo {
  available: boolean;
  provider?: string;
  providerModel?: string;
  characterCount?: number;
  elapsedSeconds?: number;
}

export interface SummaryKeyPoint {
  text: string;
  /** 시간축이 없는 전사(텍스트 파일 업로드, 2026-09-14)에서는 null이다. */
  atSeconds: number | null;
}

export interface SummaryConcept {
  term: string;
  description: string;
}

export interface SummaryCodeSnippet {
  language: string;
  code: string;
  description: string;
}

export interface SummaryActionItem {
  text: string;
  dueDate: string | null;
}

export interface SessionSummaryDetail {
  summaryId: string;
  contentMarkdown: string;
  keyPoints: SummaryKeyPoint[];
  /** @deprecated 2026-08-29 자유형식 본문(detailedNotesMarkdown) 도입 이전 요약의 유산 필드. */
  concepts: SummaryConcept[];
  /** @deprecated 2026-08-29 자유형식 본문(detailedNotesMarkdown) 도입 이전 요약의 유산 필드. */
  codeSnippets: SummaryCodeSnippet[];
  /** @deprecated 2026-08-29 자유형식 본문(detailedNotesMarkdown) 도입 이전 요약의 유산 필드. */
  actionItems: SummaryActionItem[];
  keywords: string[];
  /** LLM이 강의 내용에 맞게 자유롭게 구성한 마크다운 본문 (2026-08-29~). */
  detailedNotesMarkdown: string;
  provider: string;
  providerModel: string;
  createdAt: string;
}

export interface SessionDetailResponse {
  sessionId: string;
  title: string;
  course: string | null;
  status: SessionStatus;
  source: SessionSource;
  durationSeconds?: number;
  recordedAt?: string;
  progress?: SessionProgress;
  errorCode?: string;
  errorMessage?: string;
  transcript: SessionTranscriptInfo;
  summary: SessionSummaryDetail | null;
  pollAfterSeconds?: number;
  /** 요약까지 끝나면 오디오 원본을 지우므로(2026-08-29), 재생 가능 여부를 명시적으로 알려준다. */
  audioAvailable: boolean;
}

/** ④ GET /sessions/{id}/transcript 응답 */
export interface TranscriptSegment {
  seq: number;
  startSeconds: number;
  endSeconds: number;
  text: string;
}

export interface TranscriptResponse {
  sessionId: string;
  language: string;
  corrected: boolean;
  text: string;
  segments: TranscriptSegment[];
}

export interface GetTranscriptParams {
  corrected?: boolean;
}

/** ⑤ GET /sessions 목록 응답 */
export interface SessionListItem {
  sessionId: string;
  title: string;
  course: string | null;
  status: SessionStatus;
  durationSeconds: number | null;
  recordedAt: string;
  summaryPreview: string | null;
}

export interface SessionListResponse {
  items: SessionListItem[];
  page: number;
  size: number;
  totalCount: number;
  totalPages: number;
}

/** ⑫⑬ POST/GET /sessions/{id}/quiz — 복습 문제 자동 생성 (2026-09-01 신규). */
export type QuizStatus = "GENERATING" | "DONE" | "FAILED";

export interface QuizQuestion {
  question: string;
  answer: string;
}

export interface QuizTriggerResponse {
  sessionId: string;
  status: QuizStatus;
  pollAfterSeconds: number;
}

export interface QuizResponse {
  quizId: string;
  sessionId: string;
  status: QuizStatus;
  questions: QuizQuestion[];
  errorCode?: string;
  errorMessage?: string;
  pollAfterSeconds?: number;
  createdAt: string;
}

export interface ListSessionsParams {
  course?: string;
  status?: SessionStatus;
  /** 제목 또는 최신 요약 내용 검색 (2026-08-30). */
  q?: string;
  /** YYYY-MM-DD, recorded_at 기준 이 날짜 00:00부터. */
  dateFrom?: string;
  /** YYYY-MM-DD, recorded_at 기준 이 날짜 23:59:59까지. */
  dateTo?: string;
  page?: number;
  size?: number;
}

/** ⑥ POST /sessions/{id}/summarize 요청/응답 */
export interface SummarizeSessionRequest {
  llmProvider?: string;
}

export interface SummarizeSessionResponse {
  sessionId: string;
  status: SessionStatus;
  pollAfterSeconds: number;
}

/** ⑦ GET /sessions/{id}/export 응답 (바이너리) */
export interface ExportResult {
  blob: Blob;
  filename: string;
  contentType: string;
}

/** ⑨ GET /search 응답 */
export interface SearchResultItem {
  sessionId: string;
  title: string;
  course: string | null;
  recordedAt: string;
  matchedIn: MatchedIn;
  snippet: string;
  atSeconds: number | null;
}

export interface SearchResponse {
  query: string;
  results: SearchResultItem[];
  totalCount: number;
}

export interface SearchParams {
  q: string;
  course?: string;
  limit?: number;
}

/** ⑩ 용어집 */
export interface GlossaryTerm {
  id: number;
  term: string;
  aliases: string[];
  course: string | null;
}

export interface GlossaryListResponse {
  items: GlossaryTerm[];
}

export interface CreateGlossaryTermRequest {
  term: string;
  aliases: string[];
  course?: string | null;
}

export interface ListGlossaryParams {
  course?: string;
}

/** ⑪ PATCH /sessions/{id} 요청/응답 (P2, 제목/과목 수정) */
export interface UpdateSessionRequest {
  title?: string;
  course?: string;
  /** 2026-10-07: 세션을 다른 일자로 옮긴다. 시간대가 포함된 ISO8601이어야 한다. */
  recordedAt?: string;
}

/**
 * PATCH /sessions/{id}/summary 요청 (2026-09-14, 요약 내용 직접 수정).
 *
 * 둘 다 선택이며 보낸 필드만 갱신된다 — "핵심 주제"(keyPoints, 타임스탬프 포함)는 이
 * 엔드포인트로 건드릴 수 없다.
 */
export interface UpdateSummaryRequest {
  oneLineSummary?: string;
  detailedNotesMarkdown?: string;
}

/** ⑫ GET /health 응답 */
export interface HealthCheckItem {
  ok: boolean;
  [key: string]: unknown;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  checks: {
    database: HealthCheckItem;
    diskFreeBytes: HealthCheckItem & { value?: number };
    stt: HealthCheckItem & { provider?: string; model?: string; modelCached?: boolean };
    llm: HealthCheckItem & {
      provider?: string;
      model?: string;
      configured?: boolean;
      reachable?: boolean;
    };
    offlineMode: boolean;
    bindHost: string;
  };
}
