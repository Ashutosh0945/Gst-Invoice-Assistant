import Link from "next/link";

export default function NotFound() {
  return (
    <div className="min-h-screen grid place-items-center px-5">
      <div className="neu-card p-8 text-center max-w-md">
        <p className="font-bold text-lg">This page doesn&apos;t exist</p>
        <p className="text-sm text-ink-soft mt-2">The link may be wrong or the item was deleted.</p>
        <Link href="/app" className="btn-primary mt-5">Go home</Link>
      </div>
    </div>
  );
}
