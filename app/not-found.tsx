import Link from "next/link";
import { Card, Empty } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="pt-10">
      <Card><Empty title="That page or invoice doesn't exist" hint="It may have been removed, or the link is wrong."
        action={<Link href="/" className="btn-primary">Go to overview</Link>} /></Card>
    </div>
  );
}
