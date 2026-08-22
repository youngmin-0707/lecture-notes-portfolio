// API 클라이언트 공통 기반: base URL 해석, fetch 래퍼, 에러 클래스.
//
// Base URL은 절대 하드코딩하지 않는다 (T-30 DoD). Vite의 `VITE_API_BASE_URL` 환경변수에서
// 읽는다 (.env.example 참고). 값이 없으면 요구사항 §5.1 기본값(127.0.0.1:8765)으로 폴백한다 —
// 이 폴백은 "하드코딩된 사용"이 아니라 로컬 전용 개인 도구의 개발 편의를 위한 기본값이며,
// 실제 값은 언제나 환경변수로 덮어쓸 수 있다.
import type { ApiErrorBody, ApiErrorDetail } from "./types.ts";

const DEFAULT_SERVER_BASE_URL = "http://127.0.0.1:8765";

function resolveServerBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  const base = configured && configured.trim().length > 0 ? configured : DEFAULT_SERVER_BASE_URL;
  return base.replace(/\/+$/, "");
}

/** 서버 루트 (예: http://127.0.0.1:8765). /health 같은 비-API 엔드포인트에 사용. */
export const SERVER_BASE_URL = resolveServerBaseUrl();

/** API v1 base (예: http://127.0.0.1:8765/api/v1). §5.1 */
export const API_BASE_URL = `${SERVER_BASE_URL}/api/v1`;

/** 백엔드가 §5.1 포맷으로 내려준 에러 응답을 표현한다. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: ApiErrorDetail[];
  readonly requestId?: string;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.error.code;
    this.details = body.error.details;
    this.requestId = body.requestId;
  }
}

/** 응답 자체를 받지 못한 경우(서버 다운, 오프라인 등)를 나타낸다. */
export class NetworkError extends Error {
  readonly cause?: unknown;

  constructor(cause?: unknown) {
    super("네트워크 요청에 실패했습니다.");
    this.name = "NetworkError";
    this.cause = cause;
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as { error?: unknown }).error === "object"
  );
}

async function parseErrorBody(response: Response): Promise<ApiErrorBody> {
  try {
    const data: unknown = await response.json();
    if (isApiErrorBody(data)) {
      return data;
    }
  } catch {
    // 응답 본문이 JSON이 아닌 경우 (예: 프록시/서버 자체 500 페이지) 아래 폴백 사용
  }
  return {
    error: {
      code: "INTERNAL_ERROR",
      message: `요청이 실패했습니다 (HTTP ${response.status}).`,
    },
    requestId: "",
  };
}

async function doFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
  try {
    return await fetch(url, init);
  } catch (cause) {
    throw new NetworkError(cause);
  }
}

/** JSON을 반환하는 API 호출용 공통 함수. 2xx가 아니면 ApiError를 throw한다. */
export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await doFetch(path, init);
  if (!response.ok) {
    const body = await parseErrorBody(response);
    throw new ApiError(response.status, body);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/** 파일 다운로드(export) 등 바이너리 응답용 공통 함수. */
export async function requestBlob(
  path: string,
  init?: RequestInit,
): Promise<{ blob: Blob; response: Response }> {
  const response = await doFetch(path, init);
  if (!response.ok) {
    const body = await parseErrorBody(response);
    throw new ApiError(response.status, body);
  }
  return { blob: await response.blob(), response };
}

/** 쿼리 파라미터 중 undefined/null을 제외하고 URLSearchParams로 직렬화한다. */
export function toQueryString(
  params: Record<string, string | number | boolean | undefined | null>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}
