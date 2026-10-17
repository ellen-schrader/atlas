/**
 * Which OAuth clients the consent page will approve, judged by where the
 * authorization code would be sent.
 *
 * Supabase's OAuth server lets anyone register a client (Claude needs that to
 * connect), and the name a client registers under is whatever it says it is — we
 * saw "Claude" registered with a redirect to evil.example. The redirect URI is the
 * one thing that decides who receives the code, so it's what we check, and an
 * unknown one is refused before any approval or navigation happens.
 */

/** Claude's own connector callbacks (claude.ai, the desktop and mobile apps, Cowork). */
const CLAUDE_CALLBACKS = new Set([
  "https://claude.ai/api/mcp/auth_callback",
  "https://claude.com/api/mcp/auth_callback",
]);

/** Claude Code (and other clients on your own computer) listen on a loopback port. */
const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

export type RedirectTarget =
  | { allowed: true; kind: "claude"; label: string }
  | { allowed: true; kind: "local"; label: string }
  | { allowed: false };

export function redirectTarget(uri: string): RedirectTarget {
  let url: URL;
  try {
    url = new URL(uri);
  } catch {
    return { allowed: false };
  }
  // Credentials in a URL are a classic way to make one host read as another.
  if (url.username || url.password) return { allowed: false };

  if (url.protocol === "https:" && CLAUDE_CALLBACKS.has(`${url.origin}${url.pathname}`)) {
    return { allowed: true, kind: "claude", label: `Claude (${url.hostname})` };
  }
  // A code sent to loopback reaches only this computer, never a third party.
  if (url.protocol === "http:" && LOOPBACK_HOSTS.has(url.hostname)) {
    return { allowed: true, kind: "local", label: "Claude Code on this computer" };
  }
  return { allowed: false };
}

export function isAllowedRedirect(uri: string): boolean {
  return redirectTarget(uri).allowed;
}
