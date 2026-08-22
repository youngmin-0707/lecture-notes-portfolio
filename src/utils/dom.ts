// 여러 화면(home.ts, sessionDetail.ts)이 공유하는 작은 DOM 헬퍼.

export function el<K extends keyof HTMLElementTagNameMap = "div">(
  id: string,
): HTMLElementTagNameMap[K] | null {
  return document.getElementById(id) as HTMLElementTagNameMap[K] | null;
}

/** 사용자 입력을 HTML로 안전하게 이스케이프한다 (XSS 방지). */
export function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
