import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Loader2, Plus } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { ApiError, fetchPubMedHint, postPaper } from "@/lib/api";
import { useAppContext } from "@/routes/Layout";

/** "N more papers on PubMed name this trial": asked on request (it's a call
 *  to PubMed), with the ones the lab doesn't have, each one click to add. */
export function PubMedHint({ trialId, onAdded }: { trialId: string; onAdded: () => void }) {
  const { team } = useAppContext();
  const qc = useQueryClient();
  const toast = useToast();
  const [asked, setAsked] = useState(false);
  const hint = useQuery({
    queryKey: ["pubmed-hint", team.id, trialId],
    queryFn: () => fetchPubMedHint(team.id, trialId),
    enabled: asked,
    staleTime: 10 * 60_000,
    retry: false,
  });
  const add = useMutation({
    // Posting resolves the paper; its abstract names the trial, so Atlas links it.
    mutationFn: (pmid: string) => postPaper(`https://pubmed.ncbi.nlm.nih.gov/${pmid}/`, team.id),
    onSuccess: () => {
      toast({ message: "Added to the library. Atlas links it to this trial in a moment." });
      qc.invalidateQueries({ queryKey: ["pubmed-hint", team.id, trialId] });
      setTimeout(onAdded, 4000);
    },
    onError: (e) => toast({ message: e instanceof ApiError ? e.message : "Couldn’t add that paper." }),
  });

  if (!asked)
    return (
      <Button variant="ghost" size="sm" className="w-fit" onClick={() => setAsked(true)}>
        Check PubMed for more papers on this trial
      </Button>
    );
  if (hint.isLoading)
    return (
      <p className="flex items-center gap-2 text-sm text-muted">
        <Loader2 size={14} className="animate-spin" aria-hidden /> Asking PubMed…
      </p>
    );
  if (hint.error || !hint.data)
    return (
      <p className="text-sm text-muted">
        {hint.error instanceof ApiError ? hint.error.message : "Couldn’t reach PubMed."}
      </p>
    );
  const h = hint.data;
  return (
    <div className="flex flex-col gap-2 rounded-control border border-border p-3">
      <p className="text-sm text-fg">
        {h.count} {h.count === 1 ? "paper" : "papers"} on PubMed name this trial
        {h.not_in_lab.length > 0
          ? `; ${h.not_in_lab.length} ${h.not_in_lab.length === 1 ? "isn’t" : "aren’t"} in your library.`
          : ", all in your library."}{" "}
        <a href={h.search_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
          Open in PubMed <ExternalLink size={12} aria-hidden />
        </a>
      </p>
      {h.not_in_lab.length > 0 && (
        <ul className="divide-y divide-border">
          {h.not_in_lab.map((p) => (
            <li key={p.pmid} className="flex items-start gap-3 py-2">
              <div className="min-w-0 flex-1">
                <a
                  href={`https://pubmed.ncbi.nlm.nih.gov/${p.pmid}/`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-fg hover:text-accent"
                >
                  {p.title}
                </a>
                <div className="text-meta text-muted">{[p.journal, p.year].filter(Boolean).join(" · ")}</div>
              </div>
              <Button
                size="sm"
                variant="secondary"
                disabled={add.isPending}
                onClick={() => add.mutate(p.pmid)}
                aria-label={`Add ${p.title} to the library`}
              >
                <Plus size={14} aria-hidden /> Add
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
