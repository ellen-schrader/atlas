import type { ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { Navigate, Route, Routes } from "react-router-dom";

import { useMemberships } from "@/hooks/useMemberships";
import { useSession } from "@/hooks/useSession";
import AppShell from "@/routes/AppShell";
import Login from "@/routes/Login";
import Onboarding from "@/routes/Onboarding";

function Center({ children }: { children: ReactNode }) {
  return <div className="flex min-h-full items-center justify-center text-sm text-muted">{children}</div>;
}

export default function App() {
  const { session, loading } = useSession();

  if (loading) return <Center>Loading…</Center>;

  if (!session) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return <AuthedApp session={session} />;
}

function AuthedApp({ session }: { session: Session }) {
  const memberships = useMemberships(true);

  if (memberships.isLoading) return <Center>Loading…</Center>;

  const teams = memberships.data ?? [];
  const hasTeam = teams.length > 0;

  return (
    <Routes>
      <Route
        path="/onboarding"
        element={hasTeam ? <Navigate to="/" replace /> : <Onboarding />}
      />
      <Route
        path="/"
        element={
          hasTeam ? (
            <AppShell session={session} memberships={teams} />
          ) : (
            <Navigate to="/onboarding" replace />
          )
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
