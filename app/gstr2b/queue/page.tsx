import Link from "next/link";
import { Gstr2bQueue } from "@/components/V6Panels";

export const dynamic = "force-dynamic";

export default function QueuePage() {
  return (
    <div>
      <header className="pt-8 pb-6"><h1 className="text-[28px] md:text-[32px] font-extrabold tracking-tight">GSTR-2B work queue</h1>
        <p className="text-ink-soft mt-1">Every reconciliation result, by category. Assign, investigate and resolve discrepancies; each change is audited. <Link className="text-accent-soft" href="/gstr2b">Import a GSTR-2B</Link></p></header>
      <Gstr2bQueue />
    </div>
  );
}
