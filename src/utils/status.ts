// home.ts, sessionDetail.ts가 공유하는 세션 상태 표시 상수.
import type { SessionStatus } from "../api/index.ts";

export const STATUS_LABELS: Record<SessionStatus, string> = {
  UPLOADED: "업로드됨",
  TRANSCRIBING: "전사 중",
  TRANSCRIBED: "전사 완료",
  SUMMARIZING: "요약 중",
  DONE: "완료",
  FAILED: "실패",
};

export const PROCESSING_STATUSES: SessionStatus[] = ["TRANSCRIBING", "SUMMARIZING"];
