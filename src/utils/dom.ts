// 여러 화면(home.ts, sessionDetail.ts)이 공유하는 작은 DOM 헬퍼.

export function el<K extends keyof HTMLElementTagNameMap = "div">(
  id: string,
): HTMLElementTagNameMap[K] | null {
  return document.getElementById(id) as HTMLElementTagNameMap[K] | null;
}

/** Blob을 주어진 파일명으로 내려받게 한다 (임시 `<a download>` 클릭). */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** 사용자 입력을 HTML로 안전하게 이스케이프한다 (XSS 방지). */
export function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
