import { describe, expect, it } from "vitest";

import { treatmentName } from "./extraction";

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
