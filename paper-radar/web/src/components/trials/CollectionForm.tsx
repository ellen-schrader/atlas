import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { ChipGroup } from "@/components/trials/parts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { Textarea } from "@/components/ui/textarea";
import { type CollectionFields, createCollection } from "@/lib/collections";
import { PATIENT_GROUPS, SETTINGS, THERAPY_CLASSES } from "@/lib/trials";

export const EMPTY_COLLECTION: CollectionFields = {
  title: "",
  question: null,
  settings: [],
  patient_groups: [],
  therapy_classes: [],
  comparison: null,
};

/** Title, the question in a sentence, its tags and the comparison. */
export function CollectionForm({
  initial,
  submitLabel,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  initial: CollectionFields;
  submitLabel: string;
  pending: boolean;
  error: string | null;
  onSubmit: (fields: CollectionFields) => void;
  onCancel: () => void;
}) {
  const [f, setF] = useState<CollectionFields>(initial);
  const toggle = (key: "settings" | "patient_groups" | "therapy_classes", v: string) =>
    setF((cur) => {
      const list = cur[key] as string[];
      return { ...cur, [key]: list.includes(v) ? list.filter((x) => x !== v) : [...list, v] };
    });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (f.title.trim() && !pending) onSubmit(f);
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <label className="flex flex-col gap-1 text-sm font-medium text-fg">
        Title
        <Input
          required
          maxLength={140}
          value={f.title}
          onChange={(e) => setF({ ...f, title: e.target.value })}
          placeholder="Neoadjuvant immunotherapy in TNBC"
        />
      </label>
      <label className="flex flex-col gap-1 text-sm font-medium text-fg">
        The question
        <Textarea
          maxLength={600}
          rows={2}
          value={f.question ?? ""}
          onChange={(e) => setF({ ...f, question: e.target.value })}
          placeholder="Does adding checkpoint inhibition to neoadjuvant chemotherapy improve outcomes in early TNBC?"
        />
      </label>
      <ChipGroup
        legend="Setting"
        options={SETTINGS}
        selected={f.settings}
        onToggle={(v) => toggle("settings", v)}
      />
      <ChipGroup
        legend="Patient group"
        options={PATIENT_GROUPS}
        selected={f.patient_groups}
        onToggle={(v) => toggle("patient_groups", v)}
      />
      <ChipGroup
        legend="Therapy"
        options={THERAPY_CLASSES}
        selected={f.therapy_classes}
        onToggle={(v) => toggle("therapy_classes", v)}
        swatches
      />
      <label className="flex flex-col gap-1 text-sm font-medium text-fg">
        Comparison
        <Input
          maxLength={140}
          value={f.comparison ?? ""}
          onChange={(e) => setF({ ...f, comparison: e.target.value })}
          placeholder="Immunotherapy + chemotherapy vs chemotherapy"
        />
      </label>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={pending || !f.title.trim()}>
          {pending && <Loader2 size={14} className="animate-spin" aria-hidden />}
          {submitLabel}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** "New collection", optionally starting from trials (the compare tray, a
 *  suggestion). Opens the new collection when it's made. */
export function NewCollectionDialog({
  open,
  onClose,
  teamId,
  userId,
  initial = EMPTY_COLLECTION,
  trialIds = [],
  note,
}: {
  open: boolean;
  onClose: () => void;
  teamId: string;
  userId: string;
  initial?: CollectionFields;
  trialIds?: string[];
  /** A line under the heading ("2 trials · they don't share setting…"). */
  note?: string;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const create = useMutation({
    mutationFn: (f: CollectionFields) => createCollection(teamId, userId, f, trialIds),
    onSuccess: (id) => {
      qc.invalidateQueries({ queryKey: ["collections", teamId] });
      onClose();
      navigate(`/trials/collections/${id}`);
    },
  });
  return (
    <Modal open={open} onClose={onClose} label="New collection">
      <div className="flex flex-col gap-4 overflow-y-auto p-6 pt-14">
        <div>
          <h2 className="text-heading font-semibold text-fg">New collection</h2>
          <p className="mt-1 text-sm text-muted">
            {note ?? "A clinical question the lab follows, and the trials that answer it."}
          </p>
        </div>
        {open && (
          <CollectionForm
            initial={initial}
            submitLabel="Create collection"
            pending={create.isPending}
            error={create.error ? "Couldn’t create the collection. Try again." : null}
            onSubmit={(f) => create.mutate(f)}
            onCancel={onClose}
          />
        )}
      </div>
    </Modal>
  );
}
