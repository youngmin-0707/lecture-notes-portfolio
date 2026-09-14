// §5.3 ①~④, ⑤~⑧, ⑪ 세션 관련 엔드포인트.
import { API_BASE_URL, ApiError, NetworkError, requestBlob, requestJson, toQueryString } from "./client.ts";
import type {
  ApiErrorBody,
  CreateSessionParams,
  CreateSessionResponse,
  ExportFormat,
  ExportResult,
  GetTranscriptParams,
  ListSessionsParams,
  ProcessSessionRequest,
  ProcessSessionResponse,
  QuizResponse,
  QuizTriggerResponse,
  SessionDetailResponse,
  SessionListResponse,
  SummarizeSessionRequest,
  SummarizeSessionResponse,
  TranscriptResponse,
  UpdateSessionRequest,
  UpdateSummaryRequest,
} from "./types.ts";

/** ① POST /api/v1/sessions — 오디오 업로드 → 세션 생성 */
export async function createSession(
  params: CreateSessionParams,
): Promise<CreateSessionResponse> {
  const form = new FormData();
  form.set("file", params.file);
  if (params.title !== undefined) form.set("title", params.title);
  if (params.course !== undefined) form.set("course", params.course);
  if (params.autoProcess !== undefined) form.set("autoProcess", String(params.autoProcess));

  return requestJson<CreateSessionResponse>("/sessions", {
    method: "POST",
    body: form,
  });
}

export interface UploadProgressEvent {
  loaded: number;
  total: number;
  percent: number;
}

/**
 * ① POST /api/v1/sessions — 업로드 진행률 콜백을 받는 버전 (T-31, US-20 "업로드 중 진행률").
 *
 * `fetch`는 업로드(요청 바디 전송) 진행률 이벤트를 제공하지 않는다 — 응답을 다 받은 뒤에야
 * 완료를 알 수 있다. 그래서 이 함수만 `XMLHttpRequest`로 따로 구현한다. 에러 응답은
 * `createSession()`(fetch 기반)과 동일하게 §5.1 포맷을 파싱해 `ApiError`로 던진다.
 */
export function createSessionWithProgress(
  params: CreateSessionParams,
  onProgress?: (event: UploadProgressEvent) => void,
): Promise<CreateSessionResponse> {
  const form = new FormData();
  form.set("file", params.file);
  if (params.title !== undefined) form.set("title", params.title);
  if (params.course !== undefined) form.set("course", params.course);
  if (params.autoProcess !== undefined) form.set("autoProcess", String(params.autoProcess));

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/sessions`);

    xhr.upload.addEventListener("progress", (event) => {
      if (onProgress && event.lengthComputable) {
        onProgress({
          loaded: event.loaded,
          total: event.total,
          percent: Math.round((event.loaded / event.total) * 100),
        });
      }
    });

    xhr.addEventListener("load", () => {
      let body: unknown;
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : undefined;
      } catch {
        body = undefined;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as CreateSessionResponse);
        return;
      }
      const isErrorBody =
        typeof body === "object" &&
        body !== null &&
        "error" in body &&
        typeof (body as { error?: unknown }).error === "object";
      const errorBody: ApiErrorBody = isErrorBody
        ? (body as ApiErrorBody)
        : {
            error: { code: "INTERNAL_ERROR", message: `요청이 실패했습니다 (HTTP ${xhr.status}).` },
            requestId: "",
          };
      reject(new ApiError(xhr.status, errorBody));
    });

    xhr.addEventListener("error", () => reject(new NetworkError()));
    xhr.send(form);
  });
}

/** ② POST /api/v1/sessions/{id}/process — 전사 + 요약 실행 */
export async function processSession(
  sessionId: string,
  body: ProcessSessionRequest = {},
): Promise<ProcessSessionResponse> {
  return requestJson<ProcessSessionResponse>(`/sessions/${encodeURIComponent(sessionId)}/process`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** ③ GET /api/v1/sessions/{id} — 세션 상세 (상태/진행률/요약) */
export async function getSession(sessionId: string): Promise<SessionDetailResponse> {
  return requestJson<SessionDetailResponse>(`/sessions/${encodeURIComponent(sessionId)}`);
}

/** ④ GET /api/v1/sessions/{id}/transcript — 전사 전문 + 세그먼트 */
export async function getTranscript(
  sessionId: string,
  params: GetTranscriptParams = {},
): Promise<TranscriptResponse> {
  const qs = toQueryString({ corrected: params.corrected });
  return requestJson<TranscriptResponse>(
    `/sessions/${encodeURIComponent(sessionId)}/transcript${qs}`,
  );
}

/** ⑤ GET /api/v1/sessions — 목록 (필터/페이징) */
export async function listSessions(
  params: ListSessionsParams = {},
): Promise<SessionListResponse> {
  const qs = toQueryString({
    course: params.course,
    status: params.status,
    q: params.q,
    date_from: params.dateFrom,
    date_to: params.dateTo,
    page: params.page,
    size: params.size,
  });
  return requestJson<SessionListResponse>(`/sessions${qs}`);
}

/** ⑥ POST /api/v1/sessions/{id}/summarize — 재요약 */
export async function summarizeSession(
  sessionId: string,
  body: SummarizeSessionRequest = {},
): Promise<SummarizeSessionResponse> {
  return requestJson<SummarizeSessionResponse>(
    `/sessions/${encodeURIComponent(sessionId)}/summarize`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

function parseFilenameFromContentDisposition(header: string | null): string {
  if (!header) return "download";
  // filename*=UTF-8''... 형식과 filename="..." 형식을 모두 지원
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (utf8Match) {
    return decodeURIComponent(utf8Match[1]);
  }
  const quotedMatch = /filename="([^"]+)"/i.exec(header);
  if (quotedMatch) {
    return quotedMatch[1];
  }
  return "download";
}

/** ⑦ GET /api/v1/sessions/{id}/export — 내보내기 (md/txt/srt) */
export async function exportSession(
  sessionId: string,
  format: ExportFormat = "md",
): Promise<ExportResult> {
  const qs = toQueryString({ format });
  const { blob, response } = await requestBlob(
    `/sessions/${encodeURIComponent(sessionId)}/export${qs}`,
  );
  return {
    blob,
    filename: parseFilenameFromContentDisposition(response.headers.get("Content-Disposition")),
    contentType: response.headers.get("Content-Type") ?? "application/octet-stream",
  };
}

/**
 * GET /api/v1/sessions/{id}/audio — 원본 오디오 스트리밍 URL (T-33).
 *
 * §5.2 원 스펙에는 없던 엔드포인트다 — 세션 상세 화면(T-33)의 `<audio>` 재생을 위해
 * 백엔드에 새로 추가했다(`app/api/v1/sessions.py`). 이 함수는 fetch를 하지 않고
 * `<audio src>`/`<a href>`에 바로 넣을 수 있는 URL 문자열만 만든다 — 브라우저가 알아서
 * Range 요청을 보내며 스트리밍하므로 클라이언트 코드가 개입할 필요가 없다.
 */
export function getSessionAudioUrl(sessionId: string): string {
  return `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/audio`;
}

/** ⑧ DELETE /api/v1/sessions/{id} — 삭제 */
export async function deleteSession(sessionId: string): Promise<void> {
  await requestJson<void>(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}

/** ⑫ POST /api/v1/sessions/{id}/quiz — 복습 문제 생성 시작 (2026-09-01 신규) */
export async function createQuiz(sessionId: string): Promise<QuizTriggerResponse> {
  return requestJson<QuizTriggerResponse>(`/sessions/${encodeURIComponent(sessionId)}/quiz`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
}

/** ⑬ GET /api/v1/sessions/{id}/quiz — 가장 최근 복습 문제 조회 (2026-09-01 신규) */
export async function getQuiz(sessionId: string): Promise<QuizResponse> {
  return requestJson<QuizResponse>(`/sessions/${encodeURIComponent(sessionId)}/quiz`);
}

/** ⑪ PATCH /api/v1/sessions/{id} — 제목/과목 수정 (P2) */
export async function updateSession(
  sessionId: string,
  body: UpdateSessionRequest,
): Promise<SessionDetailResponse> {
  return requestJson<SessionDetailResponse>(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/**
 * PATCH /api/v1/sessions/{id}/summary — 요약 내용 직접 수정 (2026-09-14).
 *
 * 요약이 마음에 들지 않을 때 재요약(LLM 재호출, `resummarizeSession`)을 기다리지 않고
 * 즉시 고칠 수 있다.
 */
export async function updateSummary(
  sessionId: string,
  body: UpdateSummaryRequest,
): Promise<SessionDetailResponse> {
  return requestJson<SessionDetailResponse>(
    `/sessions/${encodeURIComponent(sessionId)}/summary`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}
