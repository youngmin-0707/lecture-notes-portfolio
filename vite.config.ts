import { defineConfig } from "vite";

export default defineConfig({
  server: {
    // Tailscale(2026-08-29)로 회사 데스크탑에서 접속할 때 필요 — `tailscale serve`가
    // 이 도메인으로 프록시해준다. 내가 소유한 tailnet 서브도메인 하나만 허용한다("." 접두사는
    // 해당 도메인과 모든 하위 도메인을 허용). `.ts.net` 전체를 허용하면 안 된다 — 다른
    // 계정의 tailnet까지 넓게 신뢰하게 되어 Vite가 공식적으로 경고하는 패턴이다.
    allowedHosts: [".example.ts.net"],
  },
  preview: {
    // 2026-08-31: 회사 네트워크에서 tailnet 경로 패킷 손실(실측 50%)이 있어, 파일 하나하나를
    // 따로 요청하는 dev 서버(HMR용 비번들 ESM)로는 페이지 로딩 자체가 거의 불가능했다.
    // 원격 접속은 여기(빌드된 번들, 요청 수가 훨씬 적음)로 받고, 로컬 개발은 그대로
    // `npm run dev`(5173)를 쓴다 — `com.lecturenotes.frontend-preview` launchd가 이 포트를
    // 띄우고, tailscale serve(443)는 이 포트를 가리킨다.
    port: 4173,
    allowedHosts: [".example.ts.net"],
  },
  test: {
    // e2e/는 @playwright/test 전용이다 (T-40) — vitest 기본 include 패턴(*.spec.ts)과
    // 겹쳐서 명시적으로 빼둔다. `npx playwright test`로 따로 실행한다.
    exclude: ["node_modules/**", "e2e/**"],
  },
});
