// 세션 날짜 이동(2026-10-07)에 쓰는 날짜 헬퍼.

/**
 * ISO 시각의 연-월-일만 `dateValue`("YYYY-MM-DD", `<input type="date">` 값)로 바꾼다.
 *
 * 시각(시:분:초)은 그대로 두므로 같은 날 세션끼리의 순서가 유지된다. 계산은 브라우저의
 * 현지 시간대로 한다 — 사용자가 고른 "몇 일"은 현지 날짜인데 서버 값은 UTC라서, UTC 날짜를
 * 그대로 바꿔치우면 오전 9시(KST) 이전 세션이 하루 어긋난 그룹에 들어간다.
 */
export function moveIsoToLocalDate(iso: string, dateValue: string): string {
  const original = new Date(iso);
  const [year, month, day] = dateValue.split("-").map(Number);
  return new Date(
    year,
    month - 1,
    day,
    original.getHours(),
    original.getMinutes(),
    original.getSeconds(),
    original.getMilliseconds(),
  ).toISOString();
}
