import { type FormEvent, useState } from "react";

import { AtlasMark } from "@/components/Brand";
import { AuthLayout } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { supabase } from "@/lib/supabase";

/** Reached from a password-reset email link. Supabase has already established a
 *  short-lived recovery session (App intercepts the PASSWORD_RECOVERY event and
 *  renders this), so setting a new password is a plain updateUser. On success
 *  the recovery session becomes a normal one and `onDone` hands control back to
 *  the app's routing. */
export default function ResetPassword({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const { error: err } = await supabase.auth.updateUser({ password });
      if (err) throw err;
      setDone(true);
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

      {done ? (
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
