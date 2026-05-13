import { describe, expect, it } from "vitest";
import { cosineSimilarity } from "../src/index.js";

describe("cosineSimilarity", () => {
  it("returns 1 for identical vectors", () => {
    expect(cosineSimilarity([1, 2, 3], [1, 2, 3])).toBeCloseTo(1);
  });

  it("returns 0 for zero vectors or mismatched dimensions", () => {
    expect(cosineSimilarity([0, 0], [1, 1])).toBe(0);
    expect(cosineSimilarity([1], [1, 2])).toBe(0);
  });

  it("returns 0 for non-finite values", () => {
    expect(cosineSimilarity([Number.NaN], [1])).toBe(0);
    expect(cosineSimilarity([Number.POSITIVE_INFINITY], [1])).toBe(0);
  });
});
