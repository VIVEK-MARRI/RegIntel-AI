import { useEffect, useRef, type ReactNode } from "react";
import { clsx } from "clsx";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  /** Accessible name (or use labelledBy for a visible heading). */
  label?: string;
  labelledBy?: string;
  children: ReactNode;
  className?: string;
}

/**
 * Shared overlay pattern for future page stages: backdrop click + Escape
 * close, body scroll lock, initial focus into the panel, aria-modal
 * labeling. Shell drawers keep their own implementation this stage;
 * new dialogs should use this instead of inventing another pattern.
 * (Full focus-trap audit belongs to Stage 17.)
 */
export function Dialog({ open, onClose, label, labelledBy, children, className }: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panelRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        tabIndex={-1}
        aria-hidden="true"
        onClick={onClose}
        className="absolute inset-0 h-full w-full cursor-default bg-slate-950/50"
      />
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-4">
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-label={label}
          aria-labelledby={labelledBy}
          tabIndex={-1}
          className={clsx(
            "card pointer-events-auto max-h-[85vh] w-full max-w-lg overflow-y-auto p-5 focus:outline-none",
            className
          )}
        >
          {children}
        </div>
      </div>
    </div>
  );
}
