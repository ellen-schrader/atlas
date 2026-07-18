import { type ReactNode, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { Navigate, Route, Routes } from "react-router-dom";

import { useMemberships } from "@/hooks/useMemberships";
import { useSession } from "@/hooks/useSession";
import { supabase } from "@/lib/supabase";
import ResetPassword from "@/routes/ResetPassword";
import Dashboard from "@/routes/Dashboard";
import Layout from "@/routes/Layout";
import Landing from "@/routes/Landing";
import Login from "@/routes/Login";
import Connect from "@/routes/Connect";
import Import from "@/routes/Import";
import MapView from "@/routes/Map";
import MapDashboard from "@/routes/MapDashboard";
import MapsLibrary from "@/routes/MapsLibrary";
import MoodBoard from "@/routes/MoodBoard";
import Onboarding from "@/routes/Onboarding";
import Papers from "@/routes/Papers";
import ReadingList from "@/routes/ReadingList";
import Settings from "@/routes/Settings";

function Center({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full items-center justify-center text-sm text-muted">{children}</div>
  );
}

export default function App() {
  const { session, loading } = useSession();

  // A password-reset link signs the user in with a short-lived recovery session,
  // which would otherwise route them straight into the app. Catch the event and
  // show the set-a-new-password screen until they've chosen one.
  const [recovering, setRecovering] = useState(false);
  useEffect(() => {
    const { data } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") setRecovering(true);
    });
    return () => data.subscription.unsubscribe();
  }, []);

  if (loading) return <Center>Loading…</Center>;

  if (recovering) return <ResetPassword onDone={() => setRecovering(false)} />;

  if (!session) {
    // Signed out, "/" is now the public landing page rather than a redirect to the
    // login form. Until this, the app had no public surface at all — there was
    // nothing to link anyone to. Signed *in*, "/" is the Dashboard (below), so the
    // split is purely on session state and neither route needs to know about the
    // other.
    return (
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    );
  }

  return <AuthedApp session={session} />;
}

function AuthedApp({ session }: { session: Session }) {
  const memberships = useMemberships(true, session.user.id);

  if (memberships.isLoading) return <Center>Loading…</Center>;

  const teams = memberships.data ?? [];
  const team = teams[0]?.teams;

  if (!team) {
    return (
      <Routes>
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="*" element={<Navigate to="/onboarding" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/onboarding" element={<Navigate to="/" replace />} />
      <Route element={<Layout session={session} team={team} />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/papers" element={<Papers />} />
        <Route path="/import" element={<Import />} />
        <Route path="/reading" element={<ReadingList />} />
        <Route path="/board" element={<MoodBoard />} />
        <Route path="/map" element={<MapView />} />
        <Route path="/maps" element={<MapsLibrary />} />
        <Route path="/maps/overview" element={<MapView />} />
        <Route path="/maps/:mapId" element={<MapDashboard />} />
        <Route path="/connect" element={<Connect />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
