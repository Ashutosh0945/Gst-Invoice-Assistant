import { Sparkles } from "lucide-react";
import { brand } from "@/lib/brand";

export function Logo({ size = "md", sub }: { size?: "sm" | "md" | "lg"; sub?: string }) {
  const box = size === "lg" ? "w-14 h-14" : size === "sm" ? "w-9 h-9" : "w-11 h-11";
  return (
    <div className="flex items-center gap-3">
      <div className={`${box} rounded-2xl bg-accent grid place-items-center shadow-glow overflow-hidden shrink-0`}>
        {brand.logoUrl
          // eslint-disable-next-line @next/next/no-img-element
          ? <img src={brand.logoUrl} alt="" className="w-full h-full object-cover" />
          : <Sparkles className="w-1/2 h-1/2 text-white" aria-hidden />}
      </div>
      <div className="leading-tight">
        <div className={`font-extrabold ${size === "lg" ? "text-2xl" : "text-lg"}`}>{brand.name}</div>
        {sub && <div className="text-[10px] tracking-[0.14em] text-ink-faint">{sub}</div>}
      </div>
    </div>
  );
}
