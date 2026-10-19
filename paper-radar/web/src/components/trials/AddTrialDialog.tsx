import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Check, Loader2, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { ApiError, addTrial, searchTrials } from "@/lib/api";
import { phaseLabel, statusLabel } from "@/lib/trials";

/** Find a breast cancer trial on ClinicalTrials.gov (NCT ID, name or words)
 *  and add it to the lab. Atlas then looks for lab papers that report it and
 *  has Claude classify it. */
export function AddTrialDialog({
  open,
  onClose,
  teamId,
}: {
  open: boolean;
  onClose: () => void;
  teamId: string;
}) {
  const qc = useQueryClient();
  const [raw, setRaw] = useState("");
  const q = useDebouncedValue(raw.trim(), 400);
  const [added, setAdded] = useState<Set<string>>(new Set());

  const results = useQuery({
    queryKey: ["trial-search", teamId, q],
    enabled: open && q.length >= 2,
    queryFn: () => searchTrials(teamId, q),
    staleTime: 60_000,
    retry: false,
  });

  const add = useMutation({
    mutationFn: (nct: string) => addTrial(teamId, nct),
    onSuccess: (_r, nct) => {
      setAdded((s) => new Set(s).add(nct));
      qc.invalidateQueries({ queryKey: ["lab-trials", teamId] });
    },
  });

  const close = () => {
    setRaw("");
    setAdded(new Set());
    add.reset();
    onClose();
  };

  return (
    <Modal open={open} onClose={close} label="Add a trial">
      <div className="flex flex-col gap-4 overflow-y-auto p-6 pt-14">
        <div>
          <h2 className="text-heading font-semibold text-fg">Add a trial</h2>
          <p className="mt-1 text-sm text-muted">
            Search ClinicalTrials.gov by NCT ID, trial name (KEYNOTE-522) or words. Breast cancer
            trials only for now.
          </p>
        </div>
        <Input
          autoFocus
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          placeholder="NCT03036488, GeparNuevo, adjuvant olaparib…"
          aria-label="Search ClinicalTrials.gov"
        />

        {results.isFetching && (
          <p className="flex items-center gap-2 text-sm text-muted">
            <Loader2 size={14} className="animate-spin" aria-hidden /> Searching
            ClinicalTrials.gov…
          </p>
        )}
        {results.error && (
          <p role="alert" className="text-sm text-danger">
            {results.error instanceof ApiError ? results.error.message : "Search failed."}
          </p>
        )}
        {results.data && !results.isFetching && results.data.length === 0 && (
          <p className="text-sm text-muted">No breast cancer trials match “{q}”.</p>
        )}
        {add.error && (
          <p role="alert" className="text-sm text-danger">
            {add.error instanceof ApiError ? add.error.message : "Couldn’t add that trial."}
          </p>
        )}

        {results.data && results.data.length > 0 && (
          <ul className="flex flex-col divide-y divide-border rounded-card border border-border">
            {results.data.map((hit) => {
              const inLab = hit.in_lab || added.has(hit.nct_id);
              const busy = add.isPending && add.variables === hit.nct_id;
              return (
                <li key={hit.nct_id} className="flex items-start gap-3 p-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-x-2">
                      <span className="font-semibold text-fg">{hit.acronym ?? hit.nct_id}</span>
                      <span className="font-mono text-meta text-muted">
                        {phaseLabel(hit.phases)} · {hit.nct_id}
                      </span>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-sm text-muted">{hit.title}</p>
                    <p className="mt-0.5 text-meta text-faint">{statusLabel(hit.status)}</p>
                  </div>
                  {inLab ? (
                    <Link
                      to={`/trials/${hit.nct_id}`}
                      onClick={close}
                      className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md px-3 text-xs font-medium text-accent hover:bg-accent-weak"
                    >
                      <Check size={14} aria-hidden /> In your lab
                    </Link>
                  ) : (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={add.isPending}
                      onClick={() => add.mutate(hit.nct_id)}
                      aria-label={`Add ${hit.acronym ?? hit.nct_id}`}
                    >
                      {busy ? (
                        <Loader2 size={14} className="animate-spin" aria-hidden />
                      ) : (
                        <Plus size={14} aria-hidden />
                      )}
                      Add
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Modal>
  );
}
