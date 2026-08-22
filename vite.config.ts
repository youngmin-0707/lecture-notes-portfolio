import { defineConfig } from "vite";

export default defineConfig({
  test: {
    // e2e/는 @playwright/test 전용이다 (T-40) — vitest 기본 include 패턴(*.spec.ts)과
    // 겹쳐서 명시적으로 빼둔다. `npx playwright test`로 따로 실행한다.
    exclude: ["node_modules/**", "e2e/**"],
  },
});
