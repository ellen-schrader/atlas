import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Check, ShieldAlert, X } from "lucide-react";

import { AuthLayout } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useSetMcpAccess } from "@/hooks/useMcpAccess";
import { redirectTarget } from "@/lib/oauthRedirects";
import { supabase } from "@/lib/supabase";
import type { Membership } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * The consent screen Supabase's OAuth server sends a user to when Claude asks to
 * connect (`/oauth/consent?authorization_id=…`). Signed-out visitors are sent
 * through login first (App), so here the user is always known.
 *
 * Anyone can register an OAuth client under any name, so the page judges a request
 * by where the authorization code would go — `redirectTarget` — and refuses anything
 * that isn't Claude's own callback or this computer, before approving or navigating
 * anywhere. The redirect Supabase hands back after approval is checked again.
 */
export default function OAuthConsent({
  memberships,
  userId,
  email,
}: {
  memberships: Membership[];
  userId: string;
  email: string;
}) {
  useDocumentTitle("Connect Claude");
  const [params] = useSearchParams();
  const authorizationId = params.get("authorization_id");
  const [outcome, setOutcome] = useState<
    "leaving" | "denied" | "refused" | "approved-elsewhere" | null
  >(null);

  const details = useQuery({
    // Per user: after "Not you? Sign out" the next account must look the request up
    // as itself, not reuse what the first one was shown.
    queryKey: ["oauth-authorization", authorizationId, userId],
    enabled: !!authorizationId,
    retry: false,
    staleTime: Infinity, // one request, one answer: don't refetch it on focus
    queryFn: async () => {
      const { data, error } = await supabase.auth.oauth.getAuthorizationDetails(authorizationId!);
      if (error) throw error;
      return data;
    },
  });

  const labs = memberships.flatMap((m) => (m.teams ? [{ ...m.teams, role: m.role }] : []));
  const access = useQuery({
    queryKey: ["mcp-access-many", labs.map((l) => l.id).join(",")],
    enabled: labs.length > 0,
    queryFn: async (): Promise<Record<string, boolean>> => {
      const { data, error } = await supabase
        .from("mcp_access")
        .select("team_id, enabled")
        .in("team_id", labs.map((l) => l.id));
      if (error) throw error;
      return Object.fromEntries((data ?? []).map((r) => [r.team_id, r.enabled]));
    },
  });

  const request = details.data && "authorization_id" in details.data ? details.data : null;
  const target = request ? redirectTarget(request.redirect_uri) : null;

  // Leave for an allowed redirect only; anything else ends here, on our page. After an
  // approval, consent is already stored — say so, rather than "nothing was shared".
  function leave(url: string | undefined, approved: boolean) {
    if (url && redirectTarget(url).allowed) {
      setOutcome("leaving");
      window.location.assign(url);
    } else {
      setOutcome(approved ? "approved-elsewhere" : "refused");
    }
  }

  // Already approved before: Supabase returns the redirect straight away.
  useEffect(() => {
    if (details.data && !("authorization_id" in details.data)) {
      leave(details.data.redirect_url, true);
    }
  }, [details.data]);

  // An unknown destination: spend the request so it can't be retried, and stay here.
  // Keyed on the request and the verdict, not the objects, so it fires once.
  const requestId = request?.authorization_id;
  const refuseRequest = target ? !target.allowed : false;
  useEffect(() => {
    if (requestId && refuseRequest) {
      void supabase.auth.oauth.denyAuthorization(requestId, { skipBrowserRedirect: true });
    }
  }, [requestId, refuseRequest]);

  const decide = useMutation({
    mutationFn: async (approve: boolean) => {
      const options = { skipBrowserRedirect: true };
      const { data, error } = approve
        ? await supabase.auth.oauth.approveAuthorization(authorizationId!, options)
        : await supabase.auth.oauth.denyAuthorization(authorizationId!, options);
      if (error) throw error;
      return { approve, url: data.redirect_url };
    },
    onSuccess: ({ approve, url }) => {
      if (!approve && !url) setOutcome("denied");
      else leave(url, approve);
    },
  });

  const anyLabOn = labs.some((l) => access.data?.[l.id]);

  let body;
  if (!authorizationId) {
    body = <Problem title="This link is incomplete">Start connecting again from Claude.</Problem>;
  } else if (details.isLoading || (details.data && !request && outcome === null)) {
    body = <p className="text-sm text-muted">Loading…</p>;
  } else if (details.error) {
    body = (
      <Problem title="This request has expired">
        Connection requests last a few minutes and work once. Start connecting again from Claude.
      </Problem>
    );
  } else if (outcome === "leaving") {
    body = <p className="text-sm text-muted">Returning you to Claude…</p>;
  } else if (outcome === "denied") {
    body = <Problem title="Not connected">You can close this tab.</Problem>;
  } else if (outcome === "approved-elsewhere") {
    body = (
      <Problem title="Connected, but not sent back" danger>
        <p>
          Atlas saved your approval but didn’t send you back, because the return address wasn’t
          Claude’s. To be safe, remove this connection in Atlas → Connect Claude → Your connected
          apps.
        </p>
      </Problem>
    );
  } else if (outcome === "refused" || (target && !target.allowed)) {
    body = (
      <Problem title="Atlas didn’t recognise this app" danger>
        <p>
          Atlas only connects to Claude, and this request would send your sign-in somewhere else
          {request ? (
            <>
              : <code className="break-all font-mono text-xs text-fg">{request.redirect_uri}</code>
            </>
          ) : null}
          . Nothing was shared.
        </p>
        <p className="mt-2">
          If you were connecting Claude, send that address to whoever runs your Atlas.
        </p>
      </Problem>
    );
  } else if (request && target?.allowed) {
    body = (
      <>
        <h2 className="text-xl font-bold tracking-tight">Connect Claude to Atlas</h2>
        <p className="mb-5 mt-1 text-sm text-muted">
          <b className="text-fg">{target.label}</b> wants to use Atlas as{" "}
          <b className="text-fg">{email}</b>.
        </p>

        <ul className="mb-5 flex flex-col gap-2 text-sm">
          <Can>Search and read the papers in your labs where Claude access is on</Can>
          <Can>Recommend what to read and summarise recent lab activity</Can>
          <Can no>post, edit or delete anything, or see other labs</Can>
        </ul>

        {access.error ? (
          <div className="mb-5 rounded-control border border-danger/40 bg-danger/5 p-3 text-sm text-muted">
            Couldn’t check your labs’ Claude access.{" "}
            <button
              type="button"
              className="font-medium text-fg underline-offset-2 hover:underline"
              onClick={() => void access.refetch()}
            >
              Try again
            </button>
          </div>
        ) : labs.length === 0 ? (
          <p className="mb-5 rounded-control border border-border bg-surface-2 p-3 text-sm text-muted">
            You’re not in a lab yet, so Claude would have nothing to read. Join or create a lab in
            Atlas first.
          </p>
        ) : (
          <div className="mb-5 flex flex-col gap-2">
            {labs.map((lab) => (
              <LabRow
                key={lab.id}
                id={lab.id}
                name={lab.name}
                owner={lab.role === "owner"}
                on={access.data?.[lab.id] ?? false}
                loading={access.isLoading}
                onChanged={() => void access.refetch()}
              />
            ))}
          </div>
        )}

        {decide.error && (
          <p className="mb-3 text-sm text-danger">
            {decide.error instanceof Error ? decide.error.message : String(decide.error)}
          </p>
        )}

        <div className="flex gap-2">
          <Button
            onClick={() => decide.mutate(true)}
            disabled={!anyLabOn || decide.isPending}
            title={anyLabOn ? undefined : "Claude access is off in all your labs"}
          >
            Allow
          </Button>
          <Button variant="secondary" onClick={() => decide.mutate(false)} disabled={decide.isPending}>
            Cancel
          </Button>
        </div>

        <p className="mt-6 text-xs text-faint">
          You can disconnect at any time from Atlas → Connect Claude.{" "}
          <button
            type="button"
            className="underline-offset-2 hover:text-fg hover:underline"
            onClick={() => void supabase.auth.signOut({ scope: "local" })}
          >
            Not {email}? Sign out
          </button>
        </p>
      </>
    );
  }

  return (
    <AuthLayout>
      {body}
    </AuthLayout>
  );
}

function LabRow({
  id,
  name,
  owner,
  on,
  loading,
  onChanged,
}: {
  id: string;
  name: string;
  owner: boolean;
  on: boolean;
  loading: boolean;
  onChanged: () => void;
}) {
  const enable = useSetMcpAccess(id);

  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-control border p-3 text-sm",
        on ? "border-accent/40 bg-accent-weak" : "border-border bg-surface",
      )}
    >
      <div className="min-w-0">
        <div className="truncate font-medium text-fg">{name}</div>
        <div className="text-xs text-muted">
          {loading
            ? "Checking…"
            : on
              ? "Claude access is on"
              : owner
                ? "Claude access is off for this lab."
                : "Claude access is off. Ask a lab owner to turn it on."}
        </div>
        {enable.error && (
          <div className="mt-1 text-xs text-danger">
            Couldn’t turn it on:{" "}
            {enable.error instanceof Error ? enable.error.message : String(enable.error)}
          </div>
        )}
      </div>
      {!loading && !on && owner && (
        <Button
          size="sm"
          variant="secondary"
          onClick={() => enable.mutate(true, { onSuccess: onChanged })}
          disabled={enable.isPending}
        >
          Turn on
        </Button>
      )}
    </div>
  );
}

function Can({ children, no }: { children: React.ReactNode; no?: boolean }) {
  const Icon = no ? X : Check;
  return (
    <li className="flex gap-2">
      <Icon size={15} className={cn("mt-0.5 shrink-0", no ? "text-muted" : "text-success")} aria-hidden />
      <span className={no ? "text-muted" : "text-fg"}>
        {no ? "Can’t " : ""}
        {children}
      </span>
    </li>
  );
}

function Problem({
  title,
  danger,
  children,
}: {
  title: string;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h2 className="flex items-center gap-2 text-xl font-bold tracking-tight">
        {danger && <ShieldAlert size={18} className="text-danger" aria-hidden />}
        {title}
      </h2>
      <div className="mt-2 text-sm text-muted">{children}</div>
    </div>
  );
}
