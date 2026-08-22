// 모든 화면이 공유하는 뼈대(상단 내비게이션 + 콘텐츠 영역).
// 실제 화면 내용은 T-31(메인)/T-33(상세)/T-34(검색)에서 채워진다. 지금은 라우팅이
// 정상 동작하는지 확인할 수 있는 placeholder만 렌더링한다.

export type NavKey = "home" | "search";

function navLink(key: NavKey, label: string, href: string, active: NavKey): string {
  const isActive = key === active;
  return `<a href="${href}" class="nav-link${isActive ? " nav-link--active" : ""}" aria-current="${isActive ? "page" : "false"}">${label}</a>`;
}

export function renderShell(active: NavKey, contentHtml: string): void {
  const app = document.querySelector<HTMLDivElement>("#app");
  if (!app) {
    throw new Error("#app 컨테이너를 찾을 수 없습니다.");
  }
  app.innerHTML = `
    <div class="layout">
      <header class="app-header">
        <span class="app-title">lecture-notes</span>
        <nav class="app-nav">
          ${navLink("home", "홈", "#/", active)}
          ${navLink("search", "검색", "#/search", active)}
        </nav>
      </header>
      <main class="app-main">
        ${contentHtml}
      </main>
    </div>
  `;
}
