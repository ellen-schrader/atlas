import { type ReactNode, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { Navigate, Route, Routes, useLocation, useSearchParams } from "react-router-dom";

import { useMemberships } from "@/hooks/useMemberships";
import { useSession } from "@/hooks/useSession";
import { supabase } from "@/lib/supabase";
import ResetPassword from "@/routes/ResetPassword";
import Dashboard from "@/routes/Dashboard";
import Layout from "@/routes/Layout";
import Landing from "@/routes/Landing";
import Login from "@/routes/Login";
import Connect from "@/routes/Connect";
import MapView from "@/routes/Map";
import MapDashboard from "@/routes/MapDashboard";
import MapsLibrary from "@/routes/MapsLibrary";
import MoodBoard from "@/routes/MoodBoard";
import Onboarding from "@/routes/Onboarding";
import PaperPage from "@/routes/PaperPage";
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
  // which would otherwise route them straight into the app. Show the set-a-new-
  // password screen until they've chosen one. Seed synchronously from the URL
  // (the recovery link carries `type=recovery` in the hash) so it can't be
  // missed if supabase-js emits PASSWORD_RECOVERY before this listener attaches;
  // the listener is the backup for when the hash was already consumed.
  const [recovering, setRecovering] = useState(
    () => typeof window !== "undefined" && window.location.hash.includes("type=recovery"),
  );
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
        {/* A shared /papers/:id link is the one signed-out URL worth keeping.
            The catch-all below replaces the URL, so without this the paper id is
            gone from the address bar and from history before the recipient has
            even logged in — and sharing is the whole point of the route. */}
        <Route path="/papers/:paperId" element={<LoginWithReturn />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    );
  }

  return <AuthedApp session={session} />;
}

/** Send a signed-out visitor to the login screen without losing where they were. */
function LoginWithReturn() {
  const { pathname, search } = useLocation();
  return <Navigate to={`/login?next=${encodeURIComponent(pathname + search)}`} replace />;
}

/** The signed-in half of the above. Only same-origin paths are honoured — `next`
 *  comes from the URL bar, so an absolute one would be an open redirect. */
function ReturnToNext() {
  const [params] = useSearchParams();
  const next = params.get("next");
  const safe = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
  return <Navigate to={safe} replace />;
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
        <Route path="/papers/:paperId" element={<PaperPage />} />
        {/* Retired: importing a .bib is a mode of the Add-paper dialog now.
            Kept as a redirect so an old bookmark lands somewhere sensible. */}
        <Route path="/import" element={<Navigate to="/papers" replace />} />
        <Route path="/reading" element={<ReadingList />} />
        <Route path="/board" element={<MoodBoard />} />
        <Route path="/map" element={<MapView />} />
        <Route path="/maps" element={<MapsLibrary />} />
        <Route path="/maps/overview" element={<MapView />} />
        <Route path="/maps/:mapId" element={<MapDashboard />} />
        <Route path="/connect" element={<Connect />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      {/* Signed in at /login: honour ?next= from LoginWithReturn, so a shared
          paper link resumes where it left off. */}
      <Route path="/login" element={<ReturnToNext />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
