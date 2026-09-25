import Link from "next/link";
import { BellRing, Camera, FileText, MessagesSquare, ShieldCheck, Sparkles } from "lucide-react";
import { brand } from "@/lib/brand";
import { Logo } from "@/components/Logo";

const FEATURES = [
  { icon: MessagesSquare, title: "Ask anything about tax", body: "“Old or new regime?” “Do I need GST?” Plain answers, worked out with this year's official rules — not guessed." },
  { icon: Camera, title: "Snap every bill", body: "We read it, check the GST, flag overcharges, sort it, and remind you before a warranty runs out." },
  { icon: FileText, title: "Send proper invoices", body: "GST-correct invoices in 30 seconds, as PDF. See who owes you, and how late they are." },
  { icon: BellRing, title: "Never miss a deadline", body: "Income tax, advance tax and GST dates worked out for you, with the amount to pay." },
];

const WHO = [
  ["Salaried & everyday", "Pick the right tax regime, keep bills safe, catch overcharges."],
  ["Shop owners", "Know how much GST you can claim back, and when returns are due."],
  ["Freelancers", "Invoice clients, chase payments, plan advance tax and 44ADA."],
];

export default function Landing() {
  return (
    <div className="min-h-screen">
      <header className="max-w-6xl mx-auto flex items-center justify-between px-5 py-5">
        <Logo />
        <nav className="flex items-center gap-3">
          <Link href="/login" className="btn">Sign in</Link>
          <Link href="/signup" className="btn-primary hidden sm:inline-flex">Get started free</Link>
        </nav>
      </header>

      <main className="max-w-6xl mx-auto px-5">
        <section className="grid lg:grid-cols-[1.1fr_1fr] gap-12 items-center pt-10 pb-20">
          <div className="rise">
            <span className="pill text-accent-soft"><Sparkles className="w-3.5 h-3.5" aria-hidden /> AI accountant</span>
            <h1 className="mt-5 text-4xl md:text-6xl font-extrabold tracking-tight leading-[1.05]">
              Tax and money help,<br />whenever you need it.
            </h1>
            <p className="mt-5 text-lg text-ink-soft max-w-xl">
              {brand.name} keeps all your bills and invoices in one place and answers your tax questions using
              your own data — so everyday questions don&apos;t need an expensive appointment.
            </p>
            <div className="flex flex-wrap gap-3 mt-8">
              <Link href="/signup" className="btn-primary px-6 py-3 text-base">Create free account</Link>
              <Link href="/login" className="btn px-6 py-3 text-base">I have an account</Link>
            </div>
          </div>
          <div className="neu-card p-5 space-y-3 rise" aria-label="Example conversation">
            <Bubble me>Old or new tax regime? My salary is 15 lakh and I put 1.5 lakh in PPF.</Bubble>
            <Bubble>The <b>new regime</b> saves you <b className="text-good">₹1,13,100</b> this year (FY 2025-26). Old regime tax: ₹2,10,600; new: ₹97,500 — even after counting your PPF.</Bubble>
            <div className="flex gap-2 pl-2">
              <span className="pill text-ink-soft"><ShieldCheck className="w-3.5 h-3.5 text-good" aria-hidden /> Worked out with official tax slabs</span>
            </div>
            <Bubble me>Was I overcharged at the showroom?</Bubble>
            <Bubble>Yes — the jacket was billed at 12% GST instead of 5%. You overpaid <b className="text-bad">₹378</b>. Here&apos;s what to tell the store.</Bubble>
          </div>
        </section>

        <section className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5 pb-20">
          {FEATURES.map((f) => (
            <div key={f.title} className="neu-card p-6">
              <div className="icon-tile"><f.icon className="w-5 h-5 text-accent-soft" aria-hidden /></div>
              <h2 className="font-bold text-lg mt-5">{f.title}</h2>
              <p className="text-sm text-ink-soft mt-2">{f.body}</p>
            </div>
          ))}
        </section>

        <section className="neu-card p-8 md:p-10 mb-20">
          <h2 className="text-2xl font-extrabold">Made for the way you earn</h2>
          <div className="grid md:grid-cols-3 gap-5 mt-6">
            {WHO.map(([t, b]) => (
              <div key={t} className="neu-inset p-5"><div className="font-bold">{t}</div><p className="text-sm text-ink-soft mt-1.5">{b}</p></div>
            ))}
          </div>
          <p className="text-xs text-ink-faint mt-8 max-w-3xl">
            {brand.name} is an AI assistant, not a chartered accountant. It handles everyday questions using verified
            tax rules; for notices, audits, disputes or large sums, it tells you to consult a qualified professional.
          </p>
        </section>
      </main>
      <footer className="text-center text-xs text-ink-faint pb-10">
        © {new Date().getFullYear()} {brand.name} · {brand.supportEmail}
      </footer>
    </div>
  );
}

function Bubble({ children, me }: { children: React.ReactNode; me?: boolean }) {
  return (
    <div className={`max-w-[88%] rounded-2xl px-4 py-3 text-sm ${me ? "ml-auto bg-accent text-white" : "bg-base shadow-neu-sm"}`}>
      {children}
    </div>
  );
}
