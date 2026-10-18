// T-40: 업로드 → 폴링 → 요약 확인 → 내보내기 전체 플로우를 실제 브라우저 + 실제 백엔드
// (실제 로컬 Whisper + 실제 로컬 Ollama, mock 없음)로 끝까지 검증한다.
//
// 이 파일이 만드는 세션은 테스트 종료 시 API로 직접 삭제한다 — 실행할 때마다 세션이
// 쌓이지 않게 하기 위함이다.
import { expect, test } from "@playwright/test";

const API_BASE_URL = "http://127.0.0.1:8765/api/v1";

/** 16비트 모노 PCM 무음 WAV를 만든다 (외부 픽스처 파일 없이 순수 버퍼로 생성). */
function makeSilentWavBuffer(durationSeconds: number, sampleRate = 16000): Buffer {
  const numSamples = Math.floor(durationSeconds * sampleRate);
  const dataSize = numSamples * 2;
  const buffer = Buffer.alloc(44 + dataSize);
  buffer.write("RIFF", 0, "ascii");
  buffer.writeUInt32LE(36 + dataSize, 4);
  buffer.write("WAVE", 8, "ascii");
  buffer.write("fmt ", 12, "ascii");
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20); // PCM
  buffer.writeUInt16LE(1, 22); // mono
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36, "ascii");
  buffer.writeUInt32LE(dataSize, 40);
  return buffer; // 44바이트 뒤는 Buffer.alloc이 이미 0으로 채워둔 무음 데이터.
}

async function deleteSession(request: import("@playwright/test").APIRequestContext, id: string) {
  await request.delete(`${API_BASE_URL}/sessions/${id}`).catch(() => {});
}

test.describe("업로드 → 폴링 → 요약 확인 → 내보내기 (T-40, US-02/US-20/US-21)", () => {
  test("전체 플로우가 콘솔/네트워크 에러 없이 끝까지 통과한다", async ({ page, request }) => {
    const consoleErrors: string[] = [];
    const failedRequests: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("requestfailed", (req) => {
      failedRequests.push(`${req.method()} ${req.url()} — ${req.failure()?.errorText}`);
    });
    page.on("pageerror", (err) => {
      consoleErrors.push(`pageerror: ${err.message}`);
    });

    let sessionId: string | undefined;

    try {
      // 1. 홈 화면 진입 + 서버 상태 확인.
      await page.goto("/");
      await expect(page.getByText(/서버 상태:/)).toContainText("ok", { timeout: 15000 });

      // 2. 업로드 (드롭존 뒤의 hidden <input type=file>에 버퍼를 직접 넣는다 — 네이티브
      //    파일 다이얼로그를 거칠 필요가 없다).
      const wavBuffer = makeSilentWavBuffer(3);
      await page.locator("#file-input").setInputFiles({
        name: "e2e-sample.wav",
        mimeType: "audio/wav",
        buffer: wavBuffer,
      });

      // 3. 업로드 완료 + 처리 시작 확인.
      await expect(page.getByText(/업로드 완료/)).toBeVisible({ timeout: 15000 });

      // 4. 세션 목록에 새 세션이 나타날 때까지 대기하고 상세 페이지로 이동한다.
      const sessionLink = page.locator(".session-card__title").first();
      await expect(sessionLink).toBeVisible({ timeout: 10000 });
      const href = await sessionLink.getAttribute("href");
      sessionId = href?.split("/sessions/")[1];
      expect(sessionId).toBeTruthy();

      await sessionLink.click();
      await expect(page).toHaveURL(new RegExp(`#/sessions/${sessionId}$`));

      // 5. 처리 완료(DONE)까지 폴링을 기다린다 — 실제 STT+LLM이 도는 구간이라 넉넉히 잡는다.
      await expect(page.locator(".badge").first()).toHaveText("완료", { timeout: 4 * 60 * 1000 });

      // 6. 요약 탭에 실제 내용이 렌더됐는지 확인.
      await expect(page.getByRole("heading", { name: "한 줄 요약" })).toBeVisible();
      await expect(page.locator(".summary-content")).not.toContainText("아직 요약이 없습니다");

      // 7. 전사 탭으로 전환 — 세그먼트 존재 여부와 무관하게 에러 없이 렌더돼야 한다.
      await page.locator('[data-tab="transcript"]').click();
      await expect(page.locator("#tab-content")).toBeVisible();

      // 8. 내보내기(md) 다운로드가 실제로 동작하는지 확인.
      const downloadPromise = page.waitForEvent("download");
      await page.locator('[data-export="md"]').click();
      const download = await downloadPromise;
      expect(download.suggestedFilename()).toMatch(/\.md$/);
    } finally {
      if (sessionId) await deleteSession(request, sessionId);
    }

    expect(consoleErrors, `콘솔 에러 발생: ${consoleErrors.join("\n")}`).toEqual([]);
    expect(failedRequests, `실패한 네트워크 요청: ${failedRequests.join("\n")}`).toEqual([]);
  });
});
