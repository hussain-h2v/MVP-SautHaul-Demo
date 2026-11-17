"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/** Minimal accessible menu button: Escape/outside click closes, arrow keys move focus. */
export function Dropdown({
  label,
  trigger,
  children,
  align = "right",
}: {
  label: string;
  trigger: React.ReactNode;
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  const [open, setOpen] = React.useState(false);
  const root = React.useRef<HTMLDivElement>(null);
  const btn = React.useRef<HTMLButtonElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setOpen(false);
      btn.current?.focus();
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const items = Array.from(root.current?.querySelectorAll<HTMLElement>("[role='menuitem'],[role='menuitemradio']") ?? []);
      if (!items.length) return;
      e.preventDefault();
      const i = items.indexOf(document.activeElement as HTMLElement);
      const next = e.key === "ArrowDown" ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
      items[next].focus();
    }
  };

  return (
    <div ref={root} className="relative" onKeyDown={onKeyDown}>
      <button
        ref={btn}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-accent-soft"
      >
        {trigger}
      </button>
      {open && (
        <div
          role="menu"
          aria-label={label}
          onClick={() => setOpen(false)}
          className={cn(
            "absolute z-50 mt-2 min-w-56 rounded-lg border border-border bg-surface p-1 shadow-lg",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

export function MenuItem({
  className,
  checked,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { checked?: boolean }) {
  return (
    <button
      type="button"
      role={checked === undefined ? "menuitem" : "menuitemradio"}
      aria-checked={checked}
      className={cn(
        "flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-accent-soft",
        checked && "font-medium text-accent",
        className,
      )}
      {...props}
    />
  );
}

export function MenuLabel({ children }: { children: React.ReactNode }) {
  return <p className="px-3 pt-2 pb-1 text-xs font-medium uppercase tracking-wider text-muted">{children}</p>;
}

export function MenuSeparator() {
  return <div role="separator" className="my-1 h-px bg-border" />;
}
