import { describe, expect, it } from "vitest";
import {
  guessBatchFieldsFromStem,
  shouldAutofillIv,
  stemFromAudioFilename,
} from "./audioFilenameHints";

describe("guessBatchFieldsFromStem", () => {
  it("机构-姓名+日期", () => {
    const [iv, note] = guessBatchFieldsFromStem("迪策资本-赵治鹏20260108");
    expect(iv).toBe("赵治鹏");
    expect(note).toContain("迪策资本");
    expect(note).toContain("20260108");
  });

  it("无日期后缀", () => {
    const [iv, note] = guessBatchFieldsFromStem("迪策资本-赵治鹏");
    expect(iv).toBe("赵治鹏");
    expect(note).toBe("机构：迪策资本");
  });

  it("无连字符", () => {
    const [iv, note] = guessBatchFieldsFromStem("单场录音001");
    expect(iv).toBe("单场录音001");
    expect(note).toBe("");
  });

  it("多个连字符仅首段拆分", () => {
    const [iv, note] = guessBatchFieldsFromStem("机构A-部门B-张三20240101");
    expect(iv).toBe("部门B-张三");
    expect(note).toContain("机构A");
    expect(note).toContain("20240101");
  });

  it("空 stem", () => {
    expect(guessBatchFieldsFromStem("")).toEqual(["", ""]);
    expect(guessBatchFieldsFromStem("   ")).toEqual(["", ""]);
  });
});

describe("stemFromAudioFilename", () => {
  it("路径+扩展名", () => {
    expect(stemFromAudioFilename("x/y/迪策资本-赵治鹏20260108.m4a")).toBe("迪策资本-赵治鹏20260108");
  });
});

describe("shouldAutofillIv BUG-C", () => {
  it("空字段总是填", () => {
    expect(shouldAutofillIv("", null)).toBe(true);
    expect(shouldAutofillIv("", "赵治鹏")).toBe(true);
  });

  it("仅空白视为已填且不覆盖", () => {
    expect(shouldAutofillIv("  ", null)).toBe(false);
  });

  it("首次有值无历史不覆盖", () => {
    expect(shouldAutofillIv("手动填的名字", null)).toBe(false);
  });

  it("用户未改（等于上次自动）可覆盖", () => {
    expect(shouldAutofillIv("赵治鹏", "赵治鹏")).toBe(true);
  });

  it("用户改过不覆盖", () => {
    expect(shouldAutofillIv("李总", "赵治鹏")).toBe(false);
  });
});
