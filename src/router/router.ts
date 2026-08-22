// 아주 가벼운 해시 기반 라우터.
//
// 해시 라우팅을 선택한 이유: 이 앱은 정적 파일로 빌드해 로컬에서 그대로 열어 쓰는
// 개인용 단일 페이지 도구다(§0 D6). history API 기반 라우팅은 새로고침/직접 URL 접근 시
// 서버(또는 정적 파일 서버)가 모든 경로를 index.html로 되돌려주는 설정이 필요한데,
// 이 프로젝트는 그런 서버 설정을 두지 않는다. 해시(`#/...`)는 항상 index.html 하나로
// 해석되므로 별도 설정 없이 새로고침·직접 진입이 항상 동작한다.

export type RouteParams = Record<string, string>;
export type RouteHandler = (params: RouteParams) => void;

interface RouteDef {
  pattern: RegExp;
  keys: string[];
  handler: RouteHandler;
}

const routes: RouteDef[] = [];
let notFoundHandler: RouteHandler = () => {};

function compile(path: string): { pattern: RegExp; keys: string[] } {
  const keys: string[] = [];
  const regexBody = path
    .split("/")
    .map((segment) => {
      if (segment.startsWith(":")) {
        keys.push(segment.slice(1));
        return "([^/]+)";
      }
      return segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("/");
  return { pattern: new RegExp(`^${regexBody}$`), keys };
}

/** 라우트를 등록한다. 경로 세그먼트에 `:id`처럼 콜론을 붙이면 파라미터가 된다. */
export function addRoute(path: string, handler: RouteHandler): void {
  const { pattern, keys } = compile(path);
  routes.push({ pattern, keys, handler });
}

/** 매칭되는 라우트가 없을 때 실행할 핸들러를 등록한다. */
export function setNotFoundHandler(handler: RouteHandler): void {
  notFoundHandler = handler;
}

/** 프로그래밍적으로 다른 라우트로 이동한다. */
export function navigate(path: string): void {
  window.location.hash = path;
}

function currentHashPath(): string {
  const raw = window.location.hash.replace(/^#/, "");
  return raw === "" ? "/" : raw;
}

function resolve(): void {
  const path = currentHashPath();
  for (const route of routes) {
    const match = route.pattern.exec(path);
    if (match) {
      const params: RouteParams = {};
      route.keys.forEach((key, i) => {
        params[key] = decodeURIComponent(match[i + 1] ?? "");
      });
      route.handler(params);
      return;
    }
  }
  notFoundHandler({});
}

/** 라우터를 시작한다. hashchange 이벤트를 구독하고 현재 경로를 즉시 렌더링한다. */
export function startRouter(): void {
  window.addEventListener("hashchange", resolve);
  resolve();
}
