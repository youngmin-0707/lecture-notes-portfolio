import { describe, expect, it } from "vitest";
import { ApiError, NetworkError } from "../api/client.ts";
import { getUserErrorMessage } from "./errorMessages.ts";

describe("getUserErrorMessage", () => {
  it("ApiError의 message를 그대로 사용한다", () => {
    const error = new ApiError(415, {
      error: {
        code: "UNSUPPORTED_AUDIO_FORMAT",
        message: "지원하지 않는 오디오 형식입니다.",
      },
      requestId: "req-1",
    });
    expect(getUserErrorMessage(error)).toBe("지원하지 않는 오디오 형식입니다.");
  });

  it("ApiError에 message가 없으면 코드 기반 폴백 메시지를 사용한다", () => {
    const error = new ApiError(409, {
      error: { code: "TRANSCRIPT_NOT_READY", message: "" },
      requestId: "req-2",
    });
    expect(getUserErrorMessage(error)).toBe("전사가 아직 완료되지 않았습니다.");
  });

  it("알려지지 않은 코드에는 일반 오류 메시지를 사용한다", () => {
    const error = new ApiError(500, {
      error: { code: "SOMETHING_NEW", message: "" },
      requestId: "req-3",
    });
    expect(getUserErrorMessage(error)).toBe("알 수 없는 오류가 발생했습니다.");
  });

  it("NetworkError는 서버 연결 안내 메시지로 변환한다", () => {
    expect(getUserErrorMessage(new NetworkError())).toContain("연결할 수 없습니다");
  });

  it("일반 Error 객체는 message를 그대로 사용한다", () => {
    expect(getUserErrorMessage(new Error("커스텀 에러"))).toBe("커스텀 에러");
  });

  it("예상 밖의 값에도 안전한 기본 메시지를 반환한다", () => {
    expect(getUserErrorMessage("문자열 에러")).toBe("알 수 없는 오류가 발생했습니다.");
    expect(getUserErrorMessage(undefined)).toBe("알 수 없는 오류가 발생했습니다.");
  });
});
