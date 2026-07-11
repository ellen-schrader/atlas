import { Brand } from "@/components/Brand";
import { Card, CardContent } from "@/components/ui/card";

export function SetupNotice() {
  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardContent className="pt-6">
          <Brand size={24} />
          <h1 className="mt-3 text-sm font-semibold">Supabase isn’t configured</h1>
          <p className="mt-1.5 text-xs leading-relaxed text-muted">
            Create <code className="font-mono text-fg">web/.env.local</code> from{" "}
            <code className="font-mono text-fg">.env.example</code> with your project’s{" "}
            <code className="font-mono text-fg">VITE_SUPABASE_URL</code> and{" "}
            <code className="font-mono text-fg">VITE_SUPABASE_ANON_KEY</code> (Supabase dashboard →
            Settings → API), then restart{" "}
            <code className="font-mono text-fg">npm run dev</code>.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
