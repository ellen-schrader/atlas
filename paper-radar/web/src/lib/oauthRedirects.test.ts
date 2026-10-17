import { describe, expect, it } from "vitest";

import { isAllowedRedirect, redirectTarget } from "./oauthRedirects";

describe("redirectTarget", () => {
  it.each([
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
    "https://claude.ai/api/mcp/auth_callback?extra=1",
  ])("allows Claude's connector callback %s", (uri) => {
    expect(redirectTarget(uri)).toMatchObject({ allowed: true, kind: "claude" });
  });

  it.each([
    "http://localhost:33418/callback",
    "http://127.0.0.1:6274/oauth/callback",
    "http://[::1]:5000/cb",
  ])("allows a loopback client on this computer %s", (uri) => {
    expect(redirectTarget(uri)).toMatchObject({ allowed: true, kind: "local" });
  });

  it.each([
    // The spike's own example: a client *named* Claude sending the code elsewhere.
    ["another site", "https://evil.example/cb"],
    ["the right path on the wrong host", "https://evil.example/api/mcp/auth_callback"],
    ["a lookalike host", "https://claude.ai.evil.example/api/mcp/auth_callback"],
    ["a subdomain of claude.ai", "https://x.claude.ai/api/mcp/auth_callback"],
    ["another path on claude.ai", "https://claude.ai/somewhere/else"],
    ["plain http to claude.ai", "http://claude.ai/api/mcp/auth_callback"],
    ["credentials posing as the host", "https://claude.ai@evil.example/api/mcp/auth_callback"],
    ["credentials on claude.ai", "https://user:pw@claude.ai/api/mcp/auth_callback"],
    ["http to another computer on the network", "http://192.168.1.10:8080/cb"],
    ["a lookalike loopback name", "http://localhost.evil.example/cb"],
    ["a custom scheme", "claude://callback"],
    ["javascript", "javascript:alert(1)"],
    ["not a URL", "not a url"],
    ["empty", ""],
  ])("refuses %s", (_label, uri) => {
    expect(isAllowedRedirect(uri)).toBe(false);
  });
});
