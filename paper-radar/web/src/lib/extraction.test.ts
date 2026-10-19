import { describe, expect, it } from "vitest";

import { extractionState, firstPage, pmcUrl, treatmentName } from "./extraction";

describe("treatmentName", () => {
  it("drops doses and schedules", () => {
    expect(treatmentName("Nab-paclitaxel 125 mg/m² weekly")).toBe("Nab-paclitaxel");
    expect(treatmentName("Atezolizumab 840 mg q2w")).toBe("Atezolizumab");
    expect(treatmentName("Open-label atezolizumab 1200 mg q3w ×11 cycles")).toBe("Open-label atezolizumab");
  });
  it("keeps each drug of a combination", () => {
    expect(
      treatmentName("Dose-dense doxorubicin 60 mg/m² + cyclophosphamide 600 mg/m² q2w ×4"),
    ).toBe("Dose-dense doxorubicin + cyclophosphamide");
  });
  it("leaves names without a dose alone", () => {
    expect(treatmentName("Placebo")).toBe("Placebo");
    expect(treatmentName("Adjuvant")).toBe("Adjuvant");
    expect(treatmentName("T-DM1")).toBe("T-DM1");
  });
});

describe("treatmentName keeps names whole", () => {
  it("doesn't cut inside brackets or at digits in names", () => {
    expect(treatmentName("Trastuzumab + pertuzumab (dual HER2 blockade)")).toBe(
      "Trastuzumab + pertuzumab (dual HER2 blockade)",
    );
    expect(treatmentName("Dual anti-HER2 blockade")).toBe("Dual anti-HER2 blockade");
    expect(treatmentName("Cycles 1–4: paclitaxel + carboplatin")).toBe("Cycles 1–4: paclitaxel + carboplatin");
  });
  it("keeps every step of a sequence", () => {
    expect(treatmentName("Paclitaxel 80 mg/m² weekly ×12 then AC")).toBe("Paclitaxel then AC");
  });
});

describe("extractionState", () => {
  const f = (p: Partial<{ extraction_status: string | null; extraction_started_at: string | null; extracted_at: string | null }>) => ({
    extraction_status: null,
    extraction_started_at: null,
    extracted_at: null,
    ...p,
  });
  it("tells a live run from a stalled one", () => {
    expect(extractionState(f({ extraction_status: "running", extraction_started_at: new Date().toISOString() }))).toBe("running");
    expect(extractionState(f({ extraction_status: "running", extraction_started_at: "2026-01-01T00:00:00Z" }))).toBe("stalled");
  });
  it("puts the latest job ahead of older data", () => {
    expect(extractionState(f({ extraction_status: "queued", extracted_at: "2026-10-01T00:00:00Z" }))).toBe("queued");
    expect(extractionState(f({ extraction_status: "done", extracted_at: "2026-10-01T00:00:00Z" }))).toBe("done");
    expect(extractionState(null)).toBe("none");
  });
});

describe("pmcUrl", () => {
  it("links a Europe PMC full text to its PMC page", () => {
    expect(pmcUrl({ origin: "europepmc", storage_path: "lab/trial/PMC12283416.xml" })).toBe(
      "https://pmc.ncbi.nlm.nih.gov/articles/PMC12283416/",
    );
  });
  it("leaves uploads and odd paths alone", () => {
    expect(pmcUrl({ origin: "upload", storage_path: "lab/trial/PMC1.xml" })).toBeNull();
    expect(pmcUrl({ origin: "europepmc", storage_path: "lab/trial/paper.xml" })).toBeNull();
  });
});

describe("firstPage", () => {
  it("reads the first page a source names", () => {
    expect(firstPage("5")).toBe(5);
    expect(firstPage("p. 5–6")).toBe(5);
    expect(firstPage("S3")).toBe(3);
  });
  it("is null without one", () => {
    expect(firstPage(null)).toBeNull();
    expect(firstPage("cover")).toBeNull();
    expect(firstPage("0")).toBeNull();
  });
});
