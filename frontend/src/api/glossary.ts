// §5.3 ⑩ 용어집 관리 — GET/POST /api/v1/glossary, DELETE /api/v1/glossary/{id}
import { requestJson, toQueryString } from "./client.ts";
import type {
  CreateGlossaryTermRequest,
  GlossaryListResponse,
  GlossaryTerm,
  ListGlossaryParams,
} from "./types.ts";

export async function listGlossaryTerms(
  params: ListGlossaryParams = {},
): Promise<GlossaryListResponse> {
  const qs = toQueryString({ course: params.course });
  return requestJson<GlossaryListResponse>(`/glossary${qs}`);
}

export async function createGlossaryTerm(
  body: CreateGlossaryTermRequest,
): Promise<GlossaryTerm> {
  return requestJson<GlossaryTerm>("/glossary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteGlossaryTerm(id: number): Promise<void> {
  await requestJson<void>(`/glossary/${encodeURIComponent(String(id))}`, {
    method: "DELETE",
  });
}
