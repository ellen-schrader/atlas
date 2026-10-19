import { describe, expect, it } from "vitest";

import type { Registry } from "./trials";
import { siteCountries } from "./trials";
import impassion031 from "../../../tests/fixtures/ctgov/NCT03197935.json";

describe("siteCountries", () => {
  it("counts sites per country, most first", () => {
    const registry = {
      contactsLocationsModule: {
        locations: [
          { country: "Germany" },
          { country: "United States" },
          { country: "Germany" },
          { country: "Japan", status: "WITHDRAWN" }, // never opened
          { country: " " },
          {},
          "not a site",
        ],
      },
    } as unknown as Registry;
    expect(siteCountries(registry)).toEqual([
      { country: "Germany", sites: 2 },
      { country: "United States", sites: 1 },
    ]);
    expect(siteCountries(null)).toEqual([]);
    expect(siteCountries({})).toEqual([]);
  });
  it("reads a real record", () => {
    const countries = siteCountries(impassion031.protocolSection as Registry);
    // IMpassion031's paper reports 13 countries.
    expect(countries).toHaveLength(13);
    expect(countries[0]).toEqual({ country: "Germany", sites: 13 });
  });
});
