import { createContext, useContext, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import { FigureDetail } from "@/components/FigureDetail";
import { Modal } from "@/components/ui/modal";
import { useFigure } from "@/hooks/useFigures";

const FigureModalContext = createContext<{ openFigure: (figureId: string) => void }>({
  openFigure: () => {},
});

export const useFigureModal = () => useContext(FigureModalContext);

/** Provides `openFigure(figureId)` app-wide. The open figure lives in the URL as
 *  `?figure=<id>` — shareable, back-button closes, refresh reopens — exactly like
 *  the paper modal. Mounted inside PaperModalProvider so a figure's linked-paper
 *  chip can swap this modal out for the paper one. */
export function FigureModalProvider({
  teamId,
  userId,
  children,
}: {
  teamId: string;
  userId: string;
  children: ReactNode;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const figureId = searchParams.get("figure");

  const openFigure = (id: string) =>
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("figure", id);
      return next;
    });

  const close = () =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("figure");
        return next;
      },
      { replace: true },
    );

  const { data: figure, isLoading } = useFigure(figureId, teamId);

  return (
    <FigureModalContext.Provider value={{ openFigure }}>
      {children}
      <Modal open={figureId !== null} onClose={close} label={figure?.title ?? "Figure"}>
        {figure ? (
          <FigureDetail
            key={figure.id}
            figure={figure}
            teamId={teamId}
            userId={userId}
            onClose={close}
          />
        ) : (
          <div className="p-10 text-center text-sm text-muted">
            {isLoading ? "Loading…" : "Figure not available."}
          </div>
        )}
      </Modal>
    </FigureModalContext.Provider>
  );
}
