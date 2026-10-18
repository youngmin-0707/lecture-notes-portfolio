import { renderShell } from "./shell.ts";

export function renderNotFoundPage(): void {
  renderShell(
    "home",
    `
      <section class="placeholder">
        <h1>페이지를 찾을 수 없습니다</h1>
        <a href="#/">← 홈으로</a>
      </section>
    `,
  );
}
