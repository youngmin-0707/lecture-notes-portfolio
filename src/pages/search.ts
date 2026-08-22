// 검색 화면. 실제 검색 UI와 용어집 관리는 T-34에서 구현한다.
import { renderShell } from "./shell.ts";

export function renderSearchPage(): void {
  renderShell(
    "search",
    `
      <section class="placeholder">
        <h1>검색</h1>
        <p>전문 검색, 용어집 관리는 다음 작업(T-34)에서 채워집니다.</p>
      </section>
    `,
  );
}
