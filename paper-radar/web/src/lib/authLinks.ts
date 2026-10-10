import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/** Where password-reset emails land (Login's `redirectTo`, and the recovery
 *  email template builds its link from that). */
export const RESET_PATH = "/reset-password";

/** A dead email link, as carried from App's redirect to the page that explains it. */
export type LinkError = {
  message: string;
  /** It was a password-reset link, so the page can offer the way forward. */
  reset: boolean;
};

/** The Supabase auth error in a URL hash (`#error=…&error_code=…`), or null if
 *  there is none. A spent or expired link is by far the common case (mail
 *  scanners open links before people do); anything else gets Supabase's own
 *  description. */
export function readLinkError(hash: string, pathname: string): LinkError | null {
  const h = new URLSearchParams(hash.slice(1));
  const code = h.get("error_code");
  if (!code && !h.get("error")) return null;
  const message =
    code === "otp_expired" || h.get("error") === "access_denied"
      ? "That email link has expired or was already used."
      : sentence(h.get("error_description") || "That email link didn't work.");
  return { message, reset: pathname === RESET_PATH };
}

/** Supabase's descriptions don't end in a full stop; ours get a sentence appended. */
function sentence(s: string): string {
  const t = s.trim();
  return /[.!?]$/.test(t) ? t : `${t}.`;
}

/** The LinkError App's redirect handed this page, read once. It lives in
 *  history.state, so it's cleared straight away: otherwise a reload or a Back
 *  to this page would show it again. */
export function useLinkError(): LinkError | null {
  const location = useLocation();
  const navigate = useNavigate();
  const [linkError] = useState(
    () => (location.state as { linkError?: LinkError } | null)?.linkError ?? null,
  );
  useEffect(() => {
    if (linkError) navigate({ pathname: location.pathname, search: location.search }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return linkError;
}
