import { describe, expect, it } from "vitest";

import { bucketOf, facetItems, hasFacet, sparkPath } from "@/lib/projectFacets";
import type { Closeness } from "@/lib/projects";

const NOW = new Date("2026-11-03T12:00:00Z");

function row(
  id: string,
  state: Closeness["state"],
  tags: string[],
  lab: string | null,
  { related = true, year = 2026 }: { related?: boolean; year?: number } = {},
): Closeness {
  return {
    paper_id: id,
    post_id: `post-${id}`,
    year,
    posted_at: "2026-10-30T00:00:00Z",
    similarity: 0.8,
    nearest_id: null,
    state,
    related,
    suggested: state ? null : "close",
    via: null,
    cutoff: 0.5,
    tags,
    lab,
  };
}

describe("facetItems", () => {
  const rows = [
    row("a", "in", ["tls", "b-cells"], "Bruno TC", { year: 2024 }),
    row("b", null, ["tls"], "Bruno TC", { year: 2025 }),
    row("c", null, ["tls", "b-cells"], "Merad M"),
    row("d", "in", ["spatial"], "Merad M"),
    row("e", null, ["tls"], "Wang L", { related: false }),
  ];

  it("counts in / related / gap over the related pool only", () => {
    const tags = facetItems("tag", rows, [], "all", { now: NOW });
    const tls = tags.find((t) => t.key === "tls")!;
    expect([tls.inCount, tls.related, tls.gap]).toEqual([1, 3, 2]);
    // "spatial" appears once: left out unless followed.
    expect(tags.map((t) => t.key)).toEqual(["tls", "b-cells"]);
  });

  it("puts followed ones first, even with nothing related", () => {
    const follows = [
      { kind: "tag" as const, value: "spatial" },
      { kind: "tag" as const, value: "nk-cells" },
    ];
    const tags = facetItems("tag", rows, follows, "all", { now: NOW });
    expect(tags.slice(0, 2).map((t) => [t.key, t.followed])).toEqual([
      ["spatial", true],
      ["nk-cells", true],
    ]);
  });

  it("groups labs by last author", () => {
    const labs = facetItems("lab", rows, [], "all", { now: NOW });
    expect(labs.map((l) => [l.key, l.inCount, l.related])).toEqual([
      ["Bruno TC", 1, 2],
      ["Merad M", 1, 2],
    ]);
  });

  it("spreads the sparkline over publication years", () => {
    const tls = facetItems("tag", rows, [], "all", { now: NOW }).find((t) => t.key === "tls")!;
    expect(tls.series).toEqual([0, 0, 0, 0, 0, 1, 1, 1]);
  });
});

describe("hasFacet", () => {
  it("matches a tag or a lab", () => {
    const r = row("a", "in", ["tls"], "Bruno TC");
    expect(hasFacet(r, "tag", "tls")).toBe(true);
    expect(hasFacet(r, "lab", "Bruno TC")).toBe(true);
    expect(hasFacet(r, "lab", "Merad M")).toBe(false);
    expect(hasFacet(undefined, "tag", "tls")).toBe(false);
  });
});

describe("bucketOf", () => {
  it("places papers in the range, or nowhere", () => {
    expect(bucketOf("all", { year: 2026, posted_at: "" }, NOW)).toBe(7);
    expect(bucketOf("all", { year: 2018, posted_at: "" }, NOW)).toBe(-1);
    expect(bucketOf("year", { year: null, posted_at: "2026-11-01T00:00:00Z" }, NOW)).toBe(11);
    expect(bucketOf("year", { year: null, posted_at: "2025-12-01T00:00:00Z" }, NOW)).toBe(0);
    expect(bucketOf("year", { year: null, posted_at: "2025-11-01T00:00:00Z" }, NOW)).toBe(-1);
    expect(bucketOf("month", { year: null, posted_at: "2026-11-02T00:00:00Z" }, NOW)).toBe(5);
    expect(bucketOf("month", { year: null, posted_at: "2026-09-01T00:00:00Z" }, NOW)).toBe(-1);
  });
});

describe("sparkPath", () => {
  it("draws a flat line for no papers", () => {
    expect(sparkPath([0, 0]).line).toBe("M0.0,20.0L100.0,20.0");
  });
});
