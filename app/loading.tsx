// Shown instantly when a sidebar link is clicked, while the next page loads its data.
// (Without this, the old page stays on screen and it looks like the click didn't work.)
export default function Loading() {
  return (
    <div className="pt-8 animate-pulse" aria-busy="true" aria-label="Loading page">
      <div className="h-9 w-64 rounded-xl bg-base-raised" />
      <div className="h-4 w-96 max-w-full rounded-lg bg-base-raised mt-3" />
      <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4 mt-8">
        {[0, 1, 2, 3].map((i) => <div key={i} className="h-36 neu-card" />)}
      </div>
      <div className="h-72 neu-card mt-6" />
    </div>
  );
}
