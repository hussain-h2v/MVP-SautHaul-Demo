"use client";

import { useTranslations } from "next-intl";
import * as React from "react";
import { Label } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, children, ...props },
  ref,
) {
  return (
    <select
      ref={ref}
      className={cn(
        "h-10 w-full rounded-md border border-border bg-surface px-3 text-sm aria-[invalid=true]:border-danger",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
});

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...props }, ref) {
    return (
      <textarea
        ref={ref}
        className={cn(
          "min-h-20 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm placeholder:text-muted aria-[invalid=true]:border-danger",
          className,
        )}
        {...props}
      />
    );
  },
);

export const Checkbox = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement> & { label: React.ReactNode }
>(function Checkbox({ label, className, id, ...props }, ref) {
  const auto = React.useId();
  const cid = id ?? auto;
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <input ref={ref} id={cid} type="checkbox" className="size-4 rounded border-border accent-[var(--accent)]" {...props} />
      <Label htmlFor={cid} className="font-normal">
        {label}
      </Label>
    </div>
  );
});

/** Label + control + hint + translated validation error. `error` is a key in the "validation" namespace. */
export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
  className,
}: {
  label: string;
  htmlFor: string;
  error?: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  const t = useTranslations("validation");
  return (
    <div className={cn("space-y-1.5", className)}>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint && !error && <p className="text-xs text-muted">{hint}</p>}
      {error && (
        <p id={`${htmlFor}-err`} role="alert" className="text-xs text-danger">
          {t.has(error as "required") ? t(error as "required") : error}
        </p>
      )}
    </div>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="mb-4 rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
      {message}
    </div>
  );
}
