// 검색 + 용어집 관리 화면 (T-34, US-15, §5.3⑨/⑩).
import {
  createGlossaryTerm,
  deleteGlossaryTerm,
  listGlossaryTerms,
  search as searchApi,
  type GlossaryTerm,
  type SearchResultItem,
} from "../api/index.ts";
import { getUserErrorMessage } from "../errors/errorMessages.ts";
import { el, escapeHtml } from "../utils/dom.ts";
import { formatDate, formatTimestamp } from "../utils/format.ts";
import { renderShell } from "./shell.ts";

// 페이지를 벗어났다 돌아와도 이전 요청 결과가 뒤늦게 반영되지 않도록 다른 페이지들과
// 동일하게 세대(generation) 토큰을 쓴다.
let currentGeneration = 0;

// --- 전문 검색 (US-15) ---

function renderSearchResultCard(item: SearchResultItem): string {
  const matchedInLabel = item.matchedIn === "TRANSCRIPT" ? "전사" : "요약";
  const timestamp =
    item.atSeconds !== null
      ? `<span class="search-result-card__meta">[${formatTimestamp(item.atSeconds)}]</span>`
      : "";

  return `
    <li class="search-result-card">
      <div class="search-result-card__header">
        <span class="badge badge--matched-in">${matchedInLabel}</span>
        <a class="search-result-card__title" href="#/sessions/${encodeURIComponent(item.sessionId)}">
          ${escapeHtml(item.title)}
        </a>
        <span class="search-result-card__meta">
          ${item.course ? `${escapeHtml(item.course)} · ` : ""}${formatDate(item.recordedAt)}
        </span>
        ${timestamp}
      </div>
      <p class="search-result-card__snippet">${escapeHtml(item.snippet)}</p>
    </li>
  `;
}

function setSearchResults(html: string): void {
  const target = el("search-results");
  if (target) target.innerHTML = html;
}

async function handleSearch(generation: number): Promise<void> {
  const qInput = el<"input">("search-q");
  const courseInput = el<"input">("search-course");
  const q = qInput?.value.trim() ?? "";
  const course = courseInput?.value.trim() || undefined;

  // §5.3⑨: 2자 미만은 서버도 400을 주지만, 굳이 왕복하지 않고 클라이언트에서 먼저 안내한다.
  if (q.length < 2) {
    setSearchResults(`<p class="status status--error">검색어는 2자 이상 입력해 주세요.</p>`);
    return;
  }

  setSearchResults(`<p class="status status--loading">검색 중...</p>`);
  try {
    const result = await searchApi({ q, course });
    if (generation !== currentGeneration) return;
    if (result.results.length === 0) {
      setSearchResults(`<p class="empty-state">검색 결과가 없습니다.</p>`);
      return;
    }
    setSearchResults(`
      <p class="search-result-count">${result.totalCount}건 찾음</p>
      <ul class="search-result-list">${result.results.map(renderSearchResultCard).join("")}</ul>
    `);
  } catch (error) {
    if (generation !== currentGeneration) return;
    setSearchResults(`<p class="status status--error">${getUserErrorMessage(error)}</p>`);
  }
}

function wireSearchForm(generation: number): void {
  const form = el<"form">("search-form");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    void handleSearch(generation);
  });
}

// --- 용어집 관리 (§5.3⑩) ---

function renderGlossaryTermCard(term: GlossaryTerm): string {
  const aliasesText = term.aliases.length ? term.aliases.join(", ") : "별칭 없음";
  const courseLabel = term.course ? escapeHtml(term.course) : "전역";
  return `
    <li class="glossary-term-card">
      <span>
        <strong>${escapeHtml(term.term)}</strong>
        <span class="glossary-term-card__aliases">(${escapeHtml(aliasesText)})</span>
        · ${courseLabel}
      </span>
      <button type="button" class="btn btn--retry" data-delete-term="${term.id}">삭제</button>
    </li>
  `;
}

async function refreshGlossary(generation: number): Promise<void> {
  const target = el("glossary-list");
  if (!target) return;
  target.innerHTML = `<p class="status status--loading">불러오는 중...</p>`;
  try {
    const result = await listGlossaryTerms();
    if (generation !== currentGeneration) return;
    target.innerHTML = result.items.length
      ? `<ul class="glossary-term-list">${result.items.map(renderGlossaryTermCard).join("")}</ul>`
      : `<p class="empty-state">등록된 용어가 없습니다.</p>`;
  } catch (error) {
    if (generation !== currentGeneration) return;
    target.innerHTML = `<p class="status status--error">${getUserErrorMessage(error)}</p>`;
  }
}

function setGlossaryFormStatus(html: string): void {
  const target = el("glossary-form-status");
  if (target) target.innerHTML = html;
}

async function handleGlossaryAdd(generation: number): Promise<void> {
  const termInput = el<"input">("glossary-form-term");
  const aliasesInput = el<"input">("glossary-form-aliases");
  const courseInput = el<"input">("glossary-form-course");

  const term = termInput?.value.trim() ?? "";
  const aliases = (aliasesInput?.value ?? "")
    .split(",")
    .map((alias) => alias.trim())
    .filter(Boolean);
  const course = courseInput?.value.trim() || undefined;

  if (!term) {
    setGlossaryFormStatus(`<p class="status status--error">용어를 입력해 주세요.</p>`);
    return;
  }

  try {
    await createGlossaryTerm({ term, aliases, course });
    if (generation !== currentGeneration) return;
    if (termInput) termInput.value = "";
    if (aliasesInput) aliasesInput.value = "";
    if (courseInput) courseInput.value = "";
    setGlossaryFormStatus("");
    await refreshGlossary(generation);
  } catch (error) {
    if (generation !== currentGeneration) return;
    setGlossaryFormStatus(`<p class="status status--error">${getUserErrorMessage(error)}</p>`);
  }
}

async function handleGlossaryDelete(id: number, generation: number): Promise<void> {
  try {
    await deleteGlossaryTerm(id);
    if (generation !== currentGeneration) return;
    await refreshGlossary(generation);
  } catch (error) {
    if (generation !== currentGeneration) return;
    setGlossaryFormStatus(`<p class="status status--error">${getUserErrorMessage(error)}</p>`);
  }
}

function wireGlossary(generation: number): void {
  const form = el<"form">("glossary-form");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    void handleGlossaryAdd(generation);
  });

  const list = el("glossary-list");
  list?.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    const button = target.closest<HTMLButtonElement>("[data-delete-term]");
    if (!button) return;
    const id = Number(button.dataset.deleteTerm);
    if (!Number.isNaN(id)) void handleGlossaryDelete(id, generation);
  });
}

export function renderSearchPage(): void {
  const generation = ++currentGeneration;

  renderShell(
    "search",
    `
      <section>
        <h1>검색</h1>
        <form id="search-form" class="search-form">
          <input
            type="search"
            id="search-q"
            placeholder="검색어 (2자 이상)"
            minlength="2"
            required
          />
          <input type="text" id="search-course" placeholder="과목 (선택)" />
          <button type="submit">검색</button>
        </form>
        <div id="search-results"></div>
      </section>
      <section class="glossary-section">
        <h2>용어집 관리</h2>
        <form id="glossary-form" class="glossary-form">
          <input type="text" id="glossary-form-term" placeholder="용어 (예: PostgreSQL)" required />
          <input type="text" id="glossary-form-aliases" placeholder="별칭 (쉼표로 구분, 선택)" />
          <input type="text" id="glossary-form-course" placeholder="과목 (선택, 비우면 전역)" />
          <button type="submit">추가</button>
        </form>
        <div id="glossary-form-status"></div>
        <div id="glossary-list"></div>
      </section>
    `,
  );

  wireSearchForm(generation);
  wireGlossary(generation);
  void refreshGlossary(generation);
}
