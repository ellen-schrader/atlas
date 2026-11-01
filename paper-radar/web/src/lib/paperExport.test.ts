import { describe, expect, it } from "vitest";

import { formatPapers } from "./paperExport";

describe("BibTeX authors", () => {
  it("braces a group name so it stays one author", () => {
    const bib = formatPapers(
      [
        {
          id: "p1",
          title: "Pembrolizumab",
          authors: ["Peter Schmid", "IMpassion031 Trial and Investigators", "CLEOPATRA Study Group, the"],
          venue: null,
          year: 2020,
          doi: null,
          url: null,
          abstract: null,
        },
      ],
      "bibtex",
    );
    expect(bib).toContain(
      "author = {Peter Schmid and {IMpassion031 Trial and Investigators} and {CLEOPATRA Study Group, the}}",
    );
  });
});
