// 에러 응답 → 화면에 보여줄 메시지 매핑 유틸.
// 백엔드가 이미 §5.1 규격대로 한국어 message를 내려주지만(app/core/errors.py),
// - 네트워크 자체가 끊긴 경우(백엔드 응답이 없음)
// - 백엔드가 예상 밖의 포맷을 내려준 경우
// 등 클라이언트에서만 벌어지는 상황도 있으므로 이 두 가지를 모두 사용자 메시지로
// 안전하게 변환하는 것이 이 모듈의 역할이다.

import { ApiError, NetworkError } from "../api/client.ts";

/**
 * 요구사항 문서 §5.1 "에러 코드 전체" 표와 동일한 코드 → 메시지 매핑.
 * 백엔드 응답에 message가 없거나 비어 있을 때의 폴백으로 사용한다.
 */
export const ERROR_CODE_MESSAGES: Record<string, string> = {
  VALIDATION_ERROR: "입력값이 올바르지 않습니다.",
  INVALID_AUDIO_FILE: "오디오 파일을 읽을 수 없습니다.",
  AUDIO_TOO_SHORT: "오디오가 너무 짧습니다.",
  AUDIO_TOO_LONG: "오디오 길이가 최대 240분을 초과합니다.",
  SESSION_NOT_FOUND: "세션을 찾을 수 없습니다.",
  INVALID_SESSION_STATE: "현재 상태에서는 수행할 수 없습니다.",
  TRANSCRIPT_NOT_READY: "전사가 아직 완료되지 않았습니다.",
  FILE_TOO_LARGE: "파일 크기가 최대 500MB를 초과합니다.",
  UNSUPPORTED_AUDIO_FORMAT: "지원하지 않는 오디오 형식입니다.",
  STT_MODEL_UNAVAILABLE: "음성 인식 모델을 준비할 수 없습니다.",
  STT_FAILED: "전사에 실패했습니다.",
  LLM_NOT_CONFIGURED: "요약 엔진이 설정되지 않았습니다.",
  LLM_QUOTA_EXCEEDED: "요약 API 사용 한도를 초과했습니다.",
  LLM_INVALID_RESPONSE: "요약 결과 형식이 올바르지 않습니다.",
  LLM_FAILED: "요약 생성에 실패했습니다.",
  INSUFFICIENT_DISK_SPACE: "디스크 여유 공간이 부족합니다.",
  INTERNAL_ERROR: "서버 오류가 발생했습니다.",
  NOT_FOUND: "대상을 찾을 수 없습니다.",
};

const NETWORK_ERROR_MESSAGE =
  "백엔드 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해 주세요 (http://127.0.0.1:8765).";

const UNKNOWN_ERROR_MESSAGE = "알 수 없는 오류가 발생했습니다.";

/**
 * 어떤 형태의 에러(ApiError, NetworkError, 그 외 알 수 없는 예외)가 와도
 * 화면에 그대로 보여줄 수 있는 한국어 메시지 한 줄로 변환한다.
 */
export function getUserErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message || ERROR_CODE_MESSAGES[error.code] || UNKNOWN_ERROR_MESSAGE;
  }
  if (error instanceof NetworkError) {
    return NETWORK_ERROR_MESSAGE;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return UNKNOWN_ERROR_MESSAGE;
}
