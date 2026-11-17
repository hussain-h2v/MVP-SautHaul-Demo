import Link from "next/link";
import { portals } from "@/lib/portals";

export default function Landing() {
  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-16">
      <p className="text-sm font-medium text-indigo-600">SetuHaul</p>
      <h1 className="mt-2 text-4xl font-semibold tracking-tight">Dock Scheduling Platform</h1>
      <p className="mt-3 max-w-xl text-slate-500">
        Drivers report delays on WhatsApp. Capacity is decided by deterministic code, never by AI.
      </p>
      <div className="mt-10 grid gap-4 sm:grid-cols-2">
        {portals.map((p) => (
          <Link
            key={p.slug}
            href={`/${p.slug}`}
            className="group rounded-xl border border-slate-200 bg-white p-6 transition hover:border-indigo-400 hover:shadow-md focus-visible:outline-2 focus-visible:outline-indigo-500 dark:border-slate-800 dark:bg-slate-900"
          >
            <p className="text-xs uppercase tracking-wider text-slate-500">{p.audience}</p>
            <p className="mt-1 text-xl font-semibold group-hover:text-indigo-600">{p.name} portal</p>
            <p className="mt-2 text-sm text-slate-500">{p.blurb}</p>
          </Link>
        ))}
      </div>
    </main>
  );
}
