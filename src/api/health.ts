// §5.3 ⑫ GET /health — 환경 점검. /api/v1 하위가 아닌 서버 루트 엔드포인트다.
import { requestJson, SERVER_BASE_URL } from "./client.ts";
import type { HealthResponse } from "./types.ts";

export async function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>(`${SERVER_BASE_URL}/health`);
}
