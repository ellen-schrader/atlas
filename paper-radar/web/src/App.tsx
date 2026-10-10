import { type ReactNode, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { Navigate, Route, Routes, useLocation, useSearchParams } from "react-router-dom";

import { useMemberships } from "@/hooks/useMemberships";
import { useSession } from "@/hooks/useSession";
import { type LinkError, RESET_PATH, readLinkError } from "@/lib/authLinks";
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

  // A password-reset link lands here in one of two shapes. The email template
  // links straight to the app with `?token_hash=…&type=recovery`, and nothing is
  // spent until the user presses Continue on the reset screen: mail scanners
  // (Safe Links and the like) open every link in an email, and Supabase's own
  // verify link is single-use, so the scanner used it up and the real click
  // came back with an error. The older shape, a recovery session already in
  // the hash, still works for emails sent before the template changed. Seed
  // both synchronously from the URL so neither can be missed if supabase-js
  // emits PASSWORD_RECOVERY before this listener attaches; the listener is the
  // backup for when the hash was already consumed. A bare RESET_PATH is the
  // reset screen too: after Continue that is the URL, and a reload there must
  // still land on the password form, not the dashboard.
  const [recovery, setRecovery] = useState<{ tokenHash: string | null } | null>(() => {
    const { search, hash, pathname } = window.location;
    const q = new URLSearchParams(search);
    const tokenHash = q.get("token_hash");
    if (tokenHash && q.get("type") === "recovery") return { tokenHash };
    if (hash.includes("type=recovery")) return { tokenHash: null };
    if (pathname === RESET_PATH && !readLinkError(hash, pathname)) return { tokenHash: null };
    return null;
  });
  useEffect(() => {
    const { data } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") setRecovery((r) => r ?? { tokenHash: null });
    });
    return () => data.subscription.unsubscribe();
  }, []);

  if (loading) return <Center>Loading…</Center>;

  if (recovery)
    return (
      <ResetPassword
        tokenHash={recovery.tokenHash}
        signedInAs={session?.user.email ?? null}
        onDone={() => setRecovery(null)}
      />
    );

  if (!session) {
    // Signed out, "/" is now the public landing page rather than a redirect to the
    // login form. Until this, the app had no public surface at all — there was
    // nothing to link anyone to. Signed *in*, "/" is the Dashboard (below), so the
    // split is purely on session state and neither route needs to know about the
    // other.
    return (
      <LinkErrorRedirect to={(e) => (e.reset ? "/login?mode=reset" : "/login")}>
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
      </LinkErrorRedirect>
    );
  }

  // Signed in, Settings is where both a password and an email change live —
  // /login would only bounce them to the dashboard.
  return (
    <LinkErrorRedirect to={() => "/settings"}>
      <AuthedApp session={session} />
    </LinkErrorRedirect>
  );
}

/** A dead email link comes back from Supabase as `#error=…&error_code=…`.
 *  Without this the user lands on the landing page or the dashboard with no
 *  explanation, and is left wondering why the link "goes to the homepage".
 *  The redirect drops the hash, so it fires once. Its own component so that
 *  only it, not App, re-renders on every navigation: `children` is the same
 *  element each time, so React skips it. */
function LinkErrorRedirect({
  to,
  children,
}: {
  to: (e: LinkError) => string;
  children: ReactNode;
}) {
  const { hash, pathname } = useLocation();
  const linkError = readLinkError(hash, pathname);
  if (linkError) return <Navigate to={to(linkError)} state={{ linkError }} replace />;
  return children;
}

const ACTIVE_LAB_KEY = "atlas.activeLab";

function readActiveLab(): string | null {
  try {
    return localStorage.getItem(ACTIVE_LAB_KEY);
  } catch {
    return null; // private mode / blocked storage: fall back to the first lab
  }
}

/** Every query in the app is scoped to the lab it was fetched for, but not every
 *  cache key says so, and an open paper modal or a half-written draft belongs to
 *  the old lab too. A reload onto Home is the one switch that can't leak any of it.
 *  False when the choice can't be stored: a reload would land back in this lab,
 *  so the menu says so instead. */
function switchLab(teamId: string): boolean {
  try {
    localStorage.setItem(ACTIVE_LAB_KEY, teamId);
  } catch {
    return false;
  }
  window.location.assign("/");
  return true;
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
  // Read once per page load, not per render: another tab switching labs writes
  // the same key, and picking that up mid-session (say on a token refresh)
  // would swap labs without the reload switchLab depends on.
  const [stored] = useState(readActiveLab);

  if (memberships.isLoading) return <Center>Loading…</Center>;

  const teams = memberships.data ?? [];
  // The lab picked from the profile menu, if it's still one of theirs; otherwise
  // the oldest membership (useMemberships orders by joined_at, so it's stable).
  const team = (teams.find((m) => m.teams?.id === stored) ?? teams[0])?.teams;

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
      <Route
        element={
          <Layout session={session} team={team} labs={teams.flatMap((m) => (m.teams ? [m.teams] : []))} onSwitchLab={switchLab} />
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/papers" element={<Papers />} />
        <Route path="/papers/:paperId" element={<PaperPage />} />
        {/* Retired: importing a .bib is a mode of the Add-paper dialog now.
            Kept as a redirect so an old bookmark lands somewhere sensible. */}
        <Route path="/import" element={<Navigate to="/papers" replace />} />
        <Route path="/reading-list" element={<ReadingList />} />
        <Route path="/gallery" element={<MoodBoard />} />
        {/* Old names for the two pages above, kept so bookmarks still land. */}
        <Route path="/reading" element={<Navigate to="/reading-list" replace />} />
        <Route path="/board" element={<Navigate to="/gallery" replace />} />
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
