import { type ReactNode, useCallback, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";

export interface ConfirmOptions {
  title: string;
  body?: ReactNode;
  confirmLabel: string;
  /** A removal or deletion: the confirm button is red. */
  danger?: boolean;
}

/** The app's own "are you sure?", in place of window.confirm: `confirm(opts)`
 *  resolves true or false, and `dialog` goes anywhere in the tree. */
export function useConfirm(): [(opts: ConfirmOptions) => Promise<boolean>, ReactNode] {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null);
  const resolve = useRef<((ok: boolean) => void) | null>(null);

  const confirm = useCallback((o: ConfirmOptions) => {
    // A second ask while one is open answers the first "no".
    resolve.current?.(false);
    setOpts(o);
    return new Promise<boolean>((r) => {
      resolve.current = r;
    });
  }, []);

  const answer = (ok: boolean) => {
    resolve.current?.(ok);
    resolve.current = null;
    setOpts(null);
  };

  const dialog = (
    <Modal open={opts !== null} onClose={() => answer(false)} label={opts?.title} className="max-w-[440px]">
      {opts && (
        <div className="flex flex-col gap-3 p-6 pt-12">
          <h2 className="text-heading font-semibold text-fg">{opts.title}</h2>
          {opts.body && <div className="text-sm text-muted">{opts.body}</div>}
          <div className="mt-2 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => answer(false)}>
              Cancel
            </Button>
            <Button
              className={opts.danger ? "bg-danger text-accent-fg hover:bg-danger hover:brightness-110" : undefined}
              onClick={() => answer(true)}
            >
              {opts.confirmLabel}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );

  return [confirm, dialog];
}
