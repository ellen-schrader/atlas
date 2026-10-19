import { describe, expect, it } from "vitest";

import {
  type CompareTrial,
  diffItems,
  enrolmentRows,
  headline,
  hrOf,
  pcrNotComparable,
  pcrOf,
  sharedHrEndpoint,
  verification,
} from "./compare";
import type { Endpoint, Extraction } from "./extraction";

function ep(p: Partial<Endpoint>): Endpoint {
  return {
    name: "pCR",
    role: "primary",
    kind: "rate",
    definition: null,
    timepoint: null,
    exp_value: null,
    ctrl_value: null,
    difference: null,
    difference_ci_low: null,
    difference_ci_high: null,
    hr: null,
    hr_ci_low: null,
    hr_ci_high: null,
    events: null,
    median_followup_months: null,
    p_value: null,
    source: null,
    ...p,
  };
}

function x(p: Partial<Extraction> = {}): Extraction {
  return {
    pico: { population: "", intervention: "", comparator: "", outcome: "" },
    design: {
      phase: null,
      randomisation_ratio: null,
      blinding: null,
      analysis_population: null,
      data_cutoff: null,
      source: null,
    },
    arms: [],
    schedule: [],
    endpoints: [],
    adverse_events: [],
    enrolment: { n_screened: null, n_randomised: null, n_analysed: null, dimensions: [], source: null },
    context: [],
    caveats: null,
    ...p,
  };
}

const trial = (name: string, ex: Extraction): CompareTrial => ({ id: name, name, extraction: ex });

describe("endpoints", () => {
  const ex = x({
    endpoints: [
      ep({ name: "pCR (PD-L1-positive)", role: "co_primary", exp_value: 69, ctrl_value: 49 }),
      ep({ name: "pCR", role: "co_primary", exp_value: 58, ctrl_value: 41, difference: 17 }),
      ep({ name: "EFS", kind: "hazard_ratio", role: "secondary", hr: 0.76 }),
      ep({ name: "OS", kind: "hazard_ratio", role: "secondary", hr: 0.56 }),
    ],
  });

  it("prefers the whole population over a subgroup", () => {
    expect(pcrOf(ex)?.exp_value).toBe(58);
  });

  it("never passes a subgroup off as the whole population", () => {
    const only = x({ endpoints: [ep({ name: "EFS (PD-L1-positive)", kind: "hazard_ratio", hr: 0.52 })] });
    expect(hrOf(only, "EFS")).toBeNull();
    const qualified = x({ endpoints: [ep({ name: "pCR (ypT0/is ypN0)", exp_value: 60, ctrl_value: 50 })] });
    expect(pcrOf(qualified)?.exp_value).toBe(60);
  });

  it("shows the plotted difference, not a differently computed one", () => {
    const stratified = x({ endpoints: [ep({ exp_value: 64.8, ctrl_value: 51.2, difference: 13.1 })] });
    expect(headline(stratified)).toBe("pCR +13.6 pp");
  });

  it("finds a hazard ratio by endpoint name", () => {
    expect(hrOf(ex, "EFS")?.hr).toBe(0.76);
    expect(hrOf(ex, "iDFS")).toBeNull();
  });

  it("writes the one-line result", () => {
    expect(headline(ex)).toBe("pCR +17 pp · EFS HR 0.76");
    expect(headline(x({ endpoints: [ep({ exp_value: 44, ctrl_value: 41 })] }))).toBe("pCR +3 pp");
    expect(headline(x())).toBe("");
  });

  it("picks the time-to-event endpoint most trials share", () => {
    const os = x({ endpoints: [ep({ name: "OS", kind: "hazard_ratio", hr: 0.8 })] });
    const efs = x({ endpoints: [ep({ name: "EFS", kind: "hazard_ratio", hr: 0.6 })] });
    expect(sharedHrEndpoint([trial("a", os), trial("b", ex), trial("c", efs)])).toBe("EFS");
    expect(sharedHrEndpoint([trial("a", x())])).toBeNull();
  });
});

describe("what differs", () => {
  const ctx = (pcr: string | null) =>
    x({ context: pcr ? [{ key: "pcr_definition", value: pcr, source: null }] : [] });

  it("flags the trial whose pCR definition is the odd one out", () => {
    const trials = [
      trial("KN522", ctx("ypT0/is ypN0")),
      trial("NeoTRIP", ctx("ypT0/is  ypN0")), // spacing doesn't count
      trial("GeparNuevo", ctx("ypT0 ypN0")),
    ];
    const [item] = diffItems(trials, ["pcr_definition"]);
    expect(item.status).toBe("differs");
    // Equal after normalising: one chip for the first two trials.
    expect(item.groups.map((g) => g.trials)).toEqual([[0, 1], [2]]);
    expect([...pcrNotComparable(trials)]).toEqual([2]);
  });

  it("is only the same when every trial reports it", () => {
    expect(diffItems([trial("a", ctx("x")), trial("b", ctx(null))], ["pcr_definition"])[0].status).toBe(
      "unknown",
    );
    expect(diffItems([trial("a", ctx("x")), trial("b", ctx("X"))], ["pcr_definition"])[0].status).toBe(
      "same",
    );
  });

  it("has no outlier in a tie, and says unknown when nobody reports it", () => {
    expect(pcrNotComparable([trial("a", ctx("x")), trial("b", ctx("y"))]).size).toBe(0);
    expect(diffItems([trial("a", ctx(null))], ["pcr_definition"])[0].status).toBe("unknown");
  });
});

describe("enrolment", () => {
  const stage = (I: number | null, II: number, III: number, allowI = true) =>
    x({
      enrolment: {
        n_screened: null,
        n_randomised: null,
        n_analysed: null,
        source: null,
        dimensions: [
          {
            key: "overall_stage",
            not_reported_pct: null,
            assay: null,
            source: null,
            categories: [
              { label: "I", eligibility: allowI ? "allowed" : "not_allowed", condition: null, overall_pct: I, exp_pct: null, ctrl_pct: null },
              { label: "II", eligibility: "allowed", condition: null, overall_pct: II, exp_pct: null, ctrl_pct: null },
              { label: "III", eligibility: "allowed", condition: null, overall_pct: III, exp_pct: null, ctrl_pct: null },
            ],
          },
        ],
      },
    });

  it("flags a share 15 pp or more from the others' mean", () => {
    const rows = enrolmentRows(
      [trial("KN522", stage(null, 74, 26, false)), trial("NeoTRIP", stage(null, 41, 59, false))],
      { overall_stage: ["I", "II", "III"] },
    );
    const [I, II, III] = rows;
    expect(I.cells.map((c) => c.state)).toEqual(["not_allowed", "not_allowed"]);
    expect(II.cells[0]).toMatchObject({ state: "value", pct: 74, flag: "up", othersMean: 41 });
    expect(III.cells[1]).toMatchObject({ flag: "up" });
    expect(II.differs && III.differs && !I.differs).toBe(true);
  });

  it("counts a category another trial excluded as 0% there", () => {
    const rows = enrolmentRows(
      [trial("Gepar", stage(24, 58, 18)), trial("KN522", stage(null, 74, 26, false))],
      { overall_stage: ["I"] },
    );
    expect(rows[0].cells[0]).toMatchObject({ pct: 24, flag: "up", othersMean: 0 });
  });

  it("says not reported for a missing dimension", () => {
    const rows = enrolmentRows([trial("a", x())], { overall_stage: ["II"] });
    expect(rows[0].cells[0].state).toBe("not_reported");
  });
});

describe("verification", () => {
  const ex = x({ endpoints: [ep({})] });
  it("reads the lab's checks", () => {
    expect(verification(ex, new Set())).toBe("Not verified");
    expect(verification(ex, new Set(["design"]))).toBe("Partly verified");
    expect(verification(ex, new Set(["design", "endpoints.0", "enrolment"]))).toBe("Verified");
  });
});
