import { describe, expect, it } from "vitest";

import { type TrialEvent, describe as say, foldEvents } from "./events";

const ev = (p: Partial<TrialEvent>): TrialEvent => ({
  id: Math.random().toString(),
  trial_id: "t1",
  kind: "values_verified",
  detail: {},
  created_at: "2026-10-19T10:00:00Z",
  actor: { display_name: "Ada" },
  ...p,
});

describe("the feed", () => {
  it("folds repeats on one trial and day into one line", () => {
    const items = foldEvents([
      ev({}),
      ev({ created_at: "2026-10-19T11:00:00Z" }),
      ev({ created_at: "2026-10-18T09:00:00Z" }),
      ev({ kind: "paper_linked" }),
    ]);
    expect(items.map((i) => [i.kind, i.count])).toEqual([
      ["values_verified", 2],
      ["values_verified", 1],
      ["paper_linked", 1],
    ]);
    expect(say(items[0])).toBe("2 value groups verified by Ada");
  });

  it("keeps people apart", () => {
    const items = foldEvents([ev({}), ev({ actor: { display_name: "Bob" } })]);
    expect(items.map((i) => say(i))).toEqual([
      "A value group verified by Ada",
      "A value group verified by Bob",
    ]);
  });

  it("says what the registry changed", () => {
    const [i] = foldEvents([ev({ kind: "status_changed", detail: { from: "RECRUITING", to: "ACTIVE_NOT_RECRUITING" } })]);
    expect(say(i)).toBe("Status changed: Recruiting → Active, not recruiting");
  });
});
