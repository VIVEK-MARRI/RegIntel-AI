import { useRef } from "react";
import { clsx } from "clsx";

export interface TabItem {
  id: string;
  label: string;
}

interface TabsProps {
  items: TabItem[];
  value: string;
  onChange: (id: string) => void;
  /** Accessible name for the tab list (required). */
  label: string;
  /** Prefix for tab/panel ids so tab-controls associations are stable. */
  idPrefix: string;
  className?: string;
}

/**
 * Shared tab pattern: roving tabindex, ArrowLeft/Right/Home/End,
 * aria-selected + underline (never color-only). Renders the tablist only —
 * pages render the active panel with role="tabpanel",
 * id={`${idPrefix}-panel-${value}`} and aria-labelledby for association.
 */
export function Tabs({ items, value, onChange, label, idPrefix, className }: TabsProps) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const focusTab = (index: number) => {
    const count = items.length;
    const next = ((index % count) + count) % count;
    tabRefs.current[next]?.focus();
    onChange(items[next].id);
  };

  const onKeyDown = (event: React.KeyboardEvent, index: number) => {
    if (event.key === "ArrowRight") {
      event.preventDefault();
      focusTab(index + 1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      focusTab(index - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusTab(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusTab(items.length - 1);
    }
  };

  return (
    <div role="tablist" aria-label={label} className={clsx("tabs", className)}>
      {items.map((item, index) => {
        const selected = item.id === value;
        return (
          <button
            key={item.id}
            ref={(el) => {
              tabRefs.current[index] = el;
            }}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${item.id}`}
            aria-selected={selected}
            aria-controls={`${idPrefix}-panel-${item.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(item.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={clsx("tab", selected && "tab-active")}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
