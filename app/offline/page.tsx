import Link from "next/link";
import { WifiOff } from "lucide-react";

export const metadata = { title: "Offline" };

export default function Offline() {
  return (
    <div className="max-w-lg mx-auto pt-16 text-center">
      <div className="icon-tile mx-auto w-16 h-16"><WifiOff className="w-7 h-7 text-warn" aria-hidden /></div>
      <h1 className="text-2xl font-extrabold mt-5">You&apos;re offline</h1>
      <p className="text-ink-soft mt-2">GST data needs a connection, so this page isn&apos;t available right now. You can still
        add invoices: they&apos;re saved on this device and uploaded automatically when you&apos;re back online.</p>
      <Link href="/upload" className="btn-primary mt-6">Add an invoice offline</Link>
    </div>
  );
}
