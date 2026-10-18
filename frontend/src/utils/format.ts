// home.ts, sessionDetail.ts, search.ts가 공유하는 포맷 헬퍼.

/** 초 단위 시간을 "MM:SS"(분은 0패딩)로 표시한다 — 오디오 타임스탬프 표기 공통 규격. */
export function formatTimestamp(seconds: number): string {
  const total = Math.max(Math.floor(seconds), 0);
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  return formatTimestamp(seconds);
}

export function formatDate(iso: string | undefined): string {
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
