import { supabase } from "@/lib/supabase";

/** Very permissive DOI matcher — enough to pull a DOI out of a pasted URL. */
const DOI_RE = /10\.\d{4,9}\/[^\s"'<>]+/i;

export function extractDoi(text: string | null | undefined): string | null {
  const m = (text ?? "").match(DOI_RE);
  return m ? m[0].replace(/[).,;]+$/, "") : null;
}

/** A DOI for provenance: from a pasted source URL first, else the linked paper. */
export async function resolveDoi(
  sourceUrl: string,
  paperId: string | null,
): Promise<string | null> {
  const fromUrl = extractDoi(sourceUrl);
  if (fromUrl) return fromUrl;
  if (paperId) {
    const { data } = await supabase.from("papers").select("doi").eq("id", paperId).maybeSingle();
    return extractDoi(data?.doi) ?? (data?.doi as string | undefined) ?? null;
  }
  return null;
}

/** Advisory licence for a DOI's *article*, via OpenAlex (public, CORS-enabled).
 *  Note: the article licence is not a guarantee for a specific figure — the
 *  caller surfaces it as a hint to confirm, not as clearance. */
export async function lookupLicense(doi: string): Promise<string | null> {
  const res = await fetch(`https://api.openalex.org/works/doi:${encodeURIComponent(doi)}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) return null;
  const work = await res.json();
  const fromLocations = (work?.locations ?? [])
    .map((l: { license?: string | null }) => l?.license)
    .find(Boolean);
  return work?.primary_location?.license ?? work?.best_oa_location?.license ?? fromLocations ?? null;
}
