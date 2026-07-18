import { type FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { AtlasMark } from "@/components/Brand";
import { AuthLayout } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";

export default function Login() {
  // The landing page's "Create your lab" CTA links to ?mode=signup. Without this it
  // would promise sign-up and deliver the log-in form — a password the visitor
  // doesn't have yet.
  const [params] = useSearchParams();
  const [mode, setMode] = useState<"login" | "signup" | "reset">(
    params.get("mode") === "signup" ? "signup" : "login",
  );
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function switchMode(m: "login" | "signup" | "reset") {
    setMode(m);
    setError(null);
    setNotice(null);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      if (mode === "signup") {
        const { data, error: err } = await supabase.auth.signUp({
          email,
          password,
          options: { data: { display_name: name } },
        });
        if (err) throw err;
        if (!data.session) setNotice("Check your email to confirm your account, then log in.");
      } else if (mode === "reset") {
        const { error: err } = await supabase.auth.resetPasswordForEmail(email, {
          redirectTo: `${window.location.origin}/reset-password`,
        });
        if (err) throw err;
        // Neutral wording: don't reveal whether an account exists for that email.
        setNotice("If an account exists for that email, a reset link is on its way.");
      } else {
        const { error: err } = await supabase.auth.signInWithPassword({ email, password });
        if (err) throw err;
      }
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

      <h2 className="font-serif text-xl font-semibold tracking-tight">
        {mode === "login" ? "Welcome back" : mode === "signup" ? "Create your account" : "Reset your password"}
      </h2>
      <p className="mb-5 mt-1 text-sm text-muted">
        {mode === "login"
          ? "Sign in to your lab."
          : mode === "signup"
            ? "Create a lab, and Atlas starts learning its taste."
            : "Enter your email and we'll send you a link to set a new password."}
      </p>

      {mode !== "reset" && (
        <div className="mb-5 flex rounded-control bg-surface-2 p-1 text-sm">
          {(["login", "signup"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => switchMode(m)}
              className={cn(
                "flex-1 rounded-md py-1.5 font-medium transition",
                mode === m ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg",
              )}
            >
              {m === "login" ? "Log in" : "Sign up"}
            </button>
          ))}
        </div>
      )}

      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        {mode === "signup" && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="name">Name</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
        )}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        {mode !== "reset" && (
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="password">Password</Label>
              {mode === "login" && (
                <button
                  type="button"
                  onClick={() => switchMode("reset")}
                  className="text-xs text-muted hover:text-fg"
                >
                  Forgot password?
                </button>
              )}
            </div>
            <Input
              id="password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
          </div>
        )}

        {error && <p className="text-xs text-danger">{error}</p>}
        {notice && <p className="text-xs text-accent">{notice}</p>}

        <Button type="submit" disabled={busy} className="mt-1">
          {busy
            ? "…"
            : mode === "login"
              ? "Log in"
              : mode === "signup"
                ? "Create account"
                : "Send reset link"}
        </Button>

        {mode === "reset" && (
          <button
            type="button"
            onClick={() => switchMode("login")}
            className="text-xs text-muted hover:text-fg"
          >
            ← Back to log in
          </button>
        )}
      </form>
    </AuthLayout>
  );
}
