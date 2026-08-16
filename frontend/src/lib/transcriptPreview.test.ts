import { describe, expect, it } from "vitest";
import { analyzeTranscript, transcriptFileLooksReadable } from "./transcriptPreview";

describe("transcriptPreview", () => {
  it("recognizes multi-speaker transcript labels", () => {
    const result = analyzeTranscript(
      "说话人A：你们的IRR预期是多少？这个赛道退出路径和后续融资节奏我们都比较关注。\n" +
      "说话人B：我们预期30%以上，核心依据是客户续费率、毛利率提升和渠道规模化带来的经营杠杆。",
    );
    expect(result.quality).toBe("good");
    expect(result.speakerCount).toBe(2);
    expect(result.speakers).toEqual(["A", "B"]);
  });

  it("warns when transcript has no speaker labels", () => {
    const result = analyzeTranscript(
      "这是一段已经转写好的会议内容，大家讨论了融资节奏、收入质量和后续尽调资料。" +
      "投资人继续追问客户留存、合同周期、现金流压力和下一轮融资安排，公司方逐项做了说明。" +
      "会议最后约定本周补充财务模型、客户名单和核心合同样本，下周再安排一次专题沟通。",
    );
    expect(result.quality).toBe("warning");
    expect(result.hasSpeakerLabels).toBe(false);
  });

  it("accepts common plain transcript file extensions", () => {
    expect(transcriptFileLooksReadable(new File(["x"], "meeting.txt"))).toBe(true);
    expect(transcriptFileLooksReadable(new File(["x"], "meeting.vtt"))).toBe(true);
    expect(transcriptFileLooksReadable(new File(["x"], "meeting.docx"))).toBe(false);
  });
});
