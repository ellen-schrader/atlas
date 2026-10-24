import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { useAppContext } from "@/routes/Layout";

/** A page behind a dark feature: home for anyone without it, nothing while the
 *  switches load, and a message (not a redirect) if they failed to — a network
 *  blip shouldn't throw someone off their page. */
export function RequireFeature({
  feature,
  children,
}: {
  feature: string;
  children: ReactNode;
}) {
  const { features, featuresLoaded, featuresFailed } = useAppContext();
  if (featuresFailed)
    return (
      <p role="alert" className="p-8 text-sm text-danger">
        Couldn’t load this page. Check your connection and reload.
      </p>
    );
  if (!featuresLoaded) return null;
  if (!features.includes(feature)) return <Navigate to="/" replace />;
  return <>{children}</>;
}
