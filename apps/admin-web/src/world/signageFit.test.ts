import { describe, expect, it } from "vitest";

import { fitSignText } from "./signageFit";

/** A fake monospace measure: every character is 0.6 em wide. */
const measure = (text: string, fontPx: number): number => text.length * fontPx * 0.6;

describe("fitSignText", () => {
  it("keeps a short code at the largest font", () => {
    expect(fitSignText("ATLAS-1", 232, 40, 18, measure)).toEqual({ text: "ATLAS-1", fontPx: 40 });
  });

  it("shrinks a longer code to fit, never below the readable minimum", () => {
    const fit = fitSignText("HARBOR-ONE-CODE", 232, 40, 18, measure);
    expect(fit.text).toBe("HARBOR-ONE-CODE");
    expect(fit.fontPx).toBeLessThan(40);
    expect(fit.fontPx).toBeGreaterThanOrEqual(18);
    expect(measure(fit.text, fit.fontPx)).toBeLessThanOrEqual(232);
  });

  it("truncates a 20-character code with an ellipsis at the minimum font and always fits", () => {
    const code = "WWWWWWWWWWWWWWWWWWWW";
    const wide = (text: string, fontPx: number): number => text.length * fontPx * 0.9; // capital W
    const fit = fitSignText(code, 232, 40, 18, wide);
    expect(fit.fontPx).toBe(18);
    expect(fit.text.endsWith("…")).toBe(true);
    expect(fit.text.length).toBeLessThan(code.length);
    expect(wide(fit.text, fit.fontPx)).toBeLessThanOrEqual(232);
  });

  it("never returns an empty sign", () => {
    expect(fitSignText("X", 1, 40, 18, measure).text.length).toBeGreaterThan(0);
  });
});
