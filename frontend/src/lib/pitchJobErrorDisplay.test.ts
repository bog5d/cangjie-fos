import { describe, expect, it } from "vitest";
import { summaryForJobRow } from "./pitchJobErrorDisplay";

describe("summaryForJobRow", () => {
  it("prefers error_summary", () => {
    expect(
      summaryForJobRow({
        error_summary: "转写服务繁忙",
        error: '{"request_id":"x"}',
      }),
    ).toBe("转写服务繁忙");
  });

  it("hides JSON-looking legacy error", () => {
    expect(
      summaryForJobRow({
        error: '{"request_id":"abc","output":{}}',
      }),
    ).toBe("处理失败，请展开查看详情或联系管理员");
  });
});
