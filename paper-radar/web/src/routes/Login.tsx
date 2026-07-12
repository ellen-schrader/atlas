import { type FormEvent, useState } from "react";
import { Compass } from "lucide-react";

import { AuthLayout } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";

export default function Login() {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-white">
          <Compass size={17} />
        </span>
        <span className="text-base font-semibold tracking-tight">Atlas</span>
      </div>

      <h2 className="text-xl font-bold tracking-tight">
        {mode === "login" ? "Welcome back" : "Create your account"}
      </h2>
      <p className="mb-5 mt-1 text-sm text-muted">
        {mode === "login" ? "Sign in to your lab’s radar." : "Start discovering papers with your lab."}
      </p>

      <div className="mb-5 flex rounded-control bg-surface-2 p-1 text-sm">
        {(["login", "signup"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={cn(
              "flex-1 rounded-md py-1.5 font-medium transition",
              mode === m ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg",
            )}
          >
            {m === "login" ? "Log in" : "Sign up"}
          </button>
        ))}
      </div>

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
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
        </div>

        {error && <p className="text-xs text-danger">{error}</p>}
        {notice && <p className="text-xs text-accent">{notice}</p>}

        <Button type="submit" disabled={busy} className="mt-1">
          {busy ? "…" : mode === "login" ? "Log in" : "Create account"}
        </Button>
      </form>
    </AuthLayout>
  );
}
