// §5.3 ⑨ GET /api/v1/search — 전문 검색
import { requestJson, toQueryString } from "./client.ts";
import type { SearchParams, SearchResponse } from "./types.ts";

export async function search(params: SearchParams): Promise<SearchResponse> {
  const qs = toQueryString({
    q: params.q,
    course: params.course,
    limit: params.limit,
  });
  return requestJson<SearchResponse>(`/search${qs}`);
}
