import Link from "next/link";
import { Logo } from "@/components/Logo";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-5 py-10">
      <Link href="/" className="mb-8"><Logo size="lg" /></Link>
      <div className="w-full max-w-md neu-card p-7 rise">{children}</div>
    </div>
  );
}
