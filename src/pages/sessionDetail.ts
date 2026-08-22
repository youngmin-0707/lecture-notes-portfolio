// 세션 상세 화면. 요약/전사 탭, 오디오 점프, 다운로드는 T-33에서 구현한다.
import type { RouteParams } from "../router/router.ts";
import { renderShell } from "./shell.ts";

export function renderSessionDetailPage(params: RouteParams): void {
  renderShell(
    "home",
    `
      <section class="placeholder">
        <h1>세션 상세</h1>
        <p>세션 ID: <code>${params.id}</code></p>
        <p>요약/전사 탭, 오디오 재생 점프, 내보내기 다운로드는 다음 작업(T-33)에서 채워집니다.</p>
        <a href="#/">← 홈으로</a>
      </section>
    `,
  );
}
