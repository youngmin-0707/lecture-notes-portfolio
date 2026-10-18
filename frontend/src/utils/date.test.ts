import { describe, expect, it } from "vitest";
import { moveIsoToLocalDate } from "./date.ts";

describe("moveIsoToLocalDate", () => {
  it("연-월-일만 바꾸고 시각은 그대로 둔다", () => {
    const original = new Date(2026, 9, 7, 10, 25, 5).toISOString();

    const moved = new Date(moveIsoToLocalDate(original, "2026-10-01"));

    expect([moved.getFullYear(), moved.getMonth() + 1, moved.getDate()]).toEqual([2026, 10, 1]);
    expect([moved.getHours(), moved.getMinutes(), moved.getSeconds()]).toEqual([10, 25, 5]);
  });

  it("UTC로는 전날인 이른 아침 세션도 고른 날짜(현지 기준)에 그대로 놓인다", () => {
    const original = new Date(2026, 9, 7, 0, 30, 0).toISOString();

    const moved = new Date(moveIsoToLocalDate(original, "2026-09-15"));

    expect([moved.getMonth() + 1, moved.getDate(), moved.getHours()]).toEqual([9, 15, 0]);
  });

  it("다른 달·다른 해로도 옮긴다", () => {
    const original = new Date(2026, 9, 31, 23, 59, 0).toISOString();

    const moved = new Date(moveIsoToLocalDate(original, "2025-02-28"));

    expect([moved.getFullYear(), moved.getMonth() + 1, moved.getDate()]).toEqual([2025, 2, 28]);
    expect(moved.getHours()).toBe(23);
  });
});
