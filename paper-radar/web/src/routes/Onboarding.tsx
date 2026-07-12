import { type FormEvent, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Brand } from "@/components/Brand";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { supabase } from "@/lib/supabase";
import { cn, slugify } from "@/lib/utils";

export default function Onboarding() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"create" | "join">("create");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    await run(async () =>
      supabase.rpc("create_team", { p_name: name.trim(), p_slug: slugify(name) }),
    );
  }

  async function onJoin(e: FormEvent) {
    e.preventDefault();
    await run(async () => supabase.rpc("join_team_by_slug", { p_slug: slugify(code) }));
  }

  async function run(action: () => Promise<{ error: unknown }>) {
    setError(null);
    setBusy(true);
    try {
      const { error: err } = await action();
      if (err) throw err;
      // Membership changed → App re-routes into the app.
      await qc.invalidateQueries({ queryKey: ["memberships"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <Card className="w-full max-w-sm">
        <CardContent className="pt-6">
          <Brand size={26} />
          <p className="mt-1 mb-5 text-xs text-muted">
            Create your lab, or join one with its code.
          </p>

          <div className="mb-5 flex rounded-md bg-surface-2 p-1 text-sm">
            {(["create", "join"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={cn(
                  "flex-1 rounded py-1.5 font-medium transition",
                  tab === t ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg",
                )}
              >
                {t === "create" ? "Create a lab" : "Join a lab"}
              </button>
            ))}
          </div>

          {tab === "create" ? (
            <form onSubmit={onCreate} className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="lab-name">Lab name</Label>
                <Input
                  id="lab-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="TME Lab"
                  required
                />
                {name.trim() && (
                  <p className="text-xs text-muted">
                    Join code: <span className="font-mono text-fg">{slugify(name)}</span>
                  </p>
                )}
              </div>
              {error && <p className="text-xs text-danger">{error}</p>}
              <Button type="submit" disabled={busy || !name.trim()}>
                {busy ? "…" : "Create lab"}
              </Button>
            </form>
          ) : (
            <form onSubmit={onJoin} className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="lab-code">Join code</Label>
                <Input
                  id="lab-code"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="tme-lab"
                  className="font-mono"
                  required
                />
              </div>
              {error && <p className="text-xs text-danger">{error}</p>}
              <Button type="submit" disabled={busy || !code.trim()}>
                {busy ? "…" : "Join lab"}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
