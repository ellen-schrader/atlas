import { type FormEvent, useState } from "react";
import { isAuthApiError } from "@supabase/supabase-js";
import { useNavigate } from "react-router-dom";

import { AtlasMark } from "@/components/Brand";
import { AuthLayout } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RESET_PATH } from "@/lib/authLinks";
import { supabase } from "@/lib/supabase";

/** Reached from a password-reset email link. With `tokenHash` (the current
 *  email template) the link hasn't been spent yet: the user presses Continue,
 *  which exchanges it for a short-lived recovery session. Doing that on a click
 *  rather than on page load is the point: mail scanners load the page but don't
 *  press buttons. Without `tokenHash`, Supabase has already established the
 *  recovery session (App intercepts the PASSWORD_RECOVERY event and renders
 *  this). Either way setting a new password is then a plain updateUser. On
 *  success the recovery session becomes a normal one and `onDone` hands control
 *  back to the app's routing. */
export default function ResetPassword({
  tokenHash,
  signedInAs,
  onDone,
}: {
  tokenHash: string | null;
  /** The signed-in account's email, if any. Without a token, a session is what
   *  makes the password form usable; with none (an old-style link Supabase
   *  rejected, or RESET_PATH opened bare) the link is dead. */
  signedInAs: string | null;
  onDone: () => void;
}) {
  const navigate = useNavigate();
  // Null until something moves it on: the starting step follows the session,
  // which can arrive a beat after this mounts (PASSWORD_RECOVERY).
  const [chosen, setStep] = useState<"confirm" | "dead" | "form" | "done" | null>(null);
  const step = chosen ?? (tokenHash ? "confirm" : signedInAs ? "form" : "dead");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onContinue() {
    if (!tokenHash) return;
    setError(null);
    setBusy(true);
    try {
      const { error: err } = await supabase.auth.verifyOtp({ token_hash: tokenHash, type: "recovery" });
      if (err) {
        // Only Supabase rejecting the token means the link is dead. A network
        // failure, rate limit or server error says nothing about the link, so
        // keep it and let them try again.
        if (isAuthApiError(err) && err.status < 500 && err.status !== 429) setStep("dead");
        else setError(err.message);
        return;
      }
      // The token is spent; keep it out of the address bar and history.
      navigate(RESET_PATH, { replace: true });
      setStep("form");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  // Signed out, ask for a new link. Signed in, there's no need for one, and
  // /login would only bounce them to the dashboard.
  function leaveDeadLink() {
    onDone();
    navigate(signedInAs ? "/settings" : "/login?mode=reset", { replace: true });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const { error: err } = await supabase.auth.updateUser({ password });
      if (err) throw err;
      setStep("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout>
      <div className="mb-6 flex items-center gap-2.5 md:hidden">
        <AtlasMark size={24} className="text-accent" />
        <span className="font-serif text-lg font-semibold tracking-tight">Atlas</span>
      </div>

      {step === "dead" ? (
        <>
          <h2 className="font-serif text-xl font-semibold tracking-tight">This link has expired</h2>
          <p className="mb-5 mt-1 text-sm text-muted">
            Reset links work once and only for an hour.{" "}
            {signedInAs
              ? `You're signed in as ${signedInAs}, so if that's the account, you can change its password in Settings instead.`
              : "Request a new one and use the latest email."}
          </p>
          <Button onClick={leaveDeadLink}>{signedInAs ? "Go to Settings" : "Send a new link"}</Button>
        </>
      ) : step === "confirm" ? (
        <>
          <h2 className="font-serif text-xl font-semibold tracking-tight">Reset your password</h2>
          <p className="mb-5 mt-1 text-sm text-muted">Continue to choose a new password.</p>
          {error && <p className="mb-3 text-xs text-danger">{error}</p>}
          <Button onClick={onContinue} disabled={busy} autoFocus>
            {busy ? "…" : error ? "Try again" : "Continue"}
          </Button>
        </>
      ) : step === "done" ? (
        <>
          <h2 className="font-serif text-xl font-semibold tracking-tight">Password updated</h2>
          <p className="mb-5 mt-1 text-sm text-muted">
            Your password has been changed and you're signed in.
          </p>
          <Button onClick={onDone}>Continue to Atlas</Button>
        </>
      ) : (
        <>
          <h2 className="font-serif text-xl font-semibold tracking-tight">Choose a new password</h2>
          <p className="mb-5 mt-1 text-sm text-muted">Set a new password for your account.</p>

          <form onSubmit={onSubmit} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-password">New password</Label>
              <Input
                id="new-password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={8}
                required
                autoFocus
              />
            </div>

            {error && <p className="text-xs text-danger">{error}</p>}

            <Button type="submit" disabled={busy} className="mt-1">
              {busy ? "…" : "Update password"}
            </Button>
          </form>
        </>
      )}
    </AuthLayout>
  );
}
