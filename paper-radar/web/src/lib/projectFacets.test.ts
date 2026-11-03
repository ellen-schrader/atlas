import { describe, expect, it } from "vitest";

import { bucketOf, facetItems, sparkPath } from "@/lib/projectFacets";
import { lastPersonAuthor, type Closeness, type PaperInfo } from "@/lib/projects";

const NOW = new Date("2026-11-03T12:00:00Z");

function row(id: string, state: Closeness["state"], related = true): Closeness {
  return {
    paper_id: id,
    post_id: `post-${id}`,
    year: 2026,
    posted_at: "2026-10-30T00:00:00Z",
    similarity: 0.8,
    nearest_id: null,
    state,
    related,
    suggested: state ? null : "close",
    via: null,
    cutoff: 0.5,
  };
}

function info(id: string, tags: string[], lab: string | null, year = 2026, posted_at = "2026-10-30T00:00:00Z"): PaperInfo {
  return { id, title: id, authors: [], venue: null, year, doi: null, url: null, abstract: null, tags, lab, posted_at };
}

describe("facetItems", () => {
  const rows = [row("a", "in"), row("b", null), row("c", null), row("d", "in"), row("e", null, false)];
  const papers = new Map(
    [
      info("a", ["tls", "b-cells"], "Bruno TC", 2024),
      info("b", ["tls"], "Bruno TC", 2025),
      info("c", ["tls", "b-cells"], "Merad M"),
      info("d", ["spatial"], "Merad M"),
      info("e", ["tls"], "Wang L"),
    ].map((p) => [p.id, p]),
  );

  it("counts in / related / gap over the related pool only", () => {
    const tags = facetItems("tag", rows, papers, [], "all", { now: NOW });
    const tls = tags.find((t) => t.key === "tls")!;
    expect([tls.inCount, tls.related, tls.gap]).toEqual([1, 3, 2]);
    // "spatial" appears once: left out unless followed.
    expect(tags.map((t) => t.key)).toEqual(["tls", "b-cells"]);
  });

  it("puts followed ones first, even with nothing related", () => {
    const tags = facetItems("tag", rows, papers, [{ kind: "tag", value: "spatial" }, { kind: "tag", value: "nk-cells" }], "all", { now: NOW });
    expect(tags.slice(0, 2).map((t) => [t.key, t.followed])).toEqual([
      ["spatial", true],
      ["nk-cells", true],
    ]);
  });

  it("groups labs by last author", () => {
    const labs = facetItems("lab", rows, papers, [], "all", { now: NOW });
    expect(labs.map((l) => [l.key, l.inCount, l.related])).toEqual([
      ["Bruno TC", 1, 2],
      ["Merad M", 1, 2],
    ]);
  });

  it("spreads the sparkline over publication years", () => {
    const tls = facetItems("tag", rows, papers, [], "all", { now: NOW }).find((t) => t.key === "tls")!;
    expect(tls.series).toEqual([0, 0, 0, 0, 0, 1, 1, 1]);
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

describe("lastPersonAuthor", () => {
  it("skips trial groups, like the server", () => {
    expect(lastPersonAuthor(["A B", "Bruno TC", "KEYNOTE-522 Investigators"])).toBe("Bruno TC");
    expect(lastPersonAuthor(["A B", "(IMpassion031 Trial"])).toBe("A B");
    expect(lastPersonAuthor([])).toBeNull();
  });
});

describe("sparkPath", () => {
  it("draws a flat line for no papers", () => {
    expect(sparkPath([0, 0]).line).toBe("M0.0,20.0L100.0,20.0");
  });
});
