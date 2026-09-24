// Dependency-free SVG charts, rendered on the server. Colours are passed in so
// every chart uses the same meaning for the same colour across the app.

export const C = {
  eligible: "#4ADE80", review: "#F5A524", atRisk: "#F87171", blocked: "#6F6E8C", accent: "#7C7CF2", info: "#60A5FA",
};

type Series = { key: string; label: string; color: string };

export function StackedBars({ data, series, height = 240, format }: {
  data: Array<Record<string, number | string>>; series: Series[]; height?: number; format: (n: number) => string;
}) {
  if (!data.length) return null;
  const W = 640, H = height, padL = 56, padB = 28, padT = 10;
  const totals = data.map((d) => series.reduce((s, x) => s + Number(d[x.key] || 0), 0));
  const max = Math.max(...totals, 1);
  const nice = niceMax(max);
  const bw = Math.min(56, ((W - padL) / data.length) * 0.5);
  const step = (W - padL) / data.length;
  const y = (v: number) => padT + (H - padT - padB) * (1 - v / nice);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Stacked bar chart">
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <g key={t}>
          <line x1={padL} x2={W} y1={y(nice * t)} y2={y(nice * t)} stroke="#2C2B48" strokeDasharray="3 5" />
          <text x={padL - 8} y={y(nice * t)} textAnchor="end" dominantBaseline="middle" fontSize="11" fill="#6F6E8C">
            {format(nice * t)}
          </text>
        </g>
      ))}
      {data.map((d, i) => {
        let acc = 0;
        const cx = padL + step * i + step / 2;
        return (
          <g key={i}>
            {series.map((s) => {
              const v = Number(d[s.key] || 0);
              if (!v) return null;
              const y0 = y(acc), y1 = y(acc + v);
              acc += v;
              return (
                <rect key={s.key} x={cx - bw / 2} y={y1} width={bw} height={Math.max(1, y0 - y1)} rx={4} fill={s.color}>
                  <title>{`${d.label}: ${s.label} ${format(v)}`}</title>
                </rect>
              );
            })}
            <text x={cx} y={H - 8} textAnchor="middle" fontSize="11" fill="#A9A8C3">{String(d.label)}</text>
          </g>
        );
      })}
    </svg>
  );
}

export function Donut({ segments, center, sub, size = 180 }: {
  segments: Array<{ label: string; value: number; color: string }>; center: string; sub?: string; size?: number;
}) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  const r = 70, sw = 18, circ = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg viewBox="0 0 180 180" width={size} height={size} role="img" aria-label={`${center} ${sub ?? ""}`}>
      <circle cx="90" cy="90" r={r} fill="none" stroke="#1A1930" strokeWidth={sw} />
      {total > 0 && segments.map((s) => {
        const len = (s.value / total) * circ;
        const el = (
          <circle key={s.label} cx="90" cy="90" r={r} fill="none" stroke={s.color} strokeWidth={sw}
            strokeDasharray={`${Math.max(0, len - 3)} ${circ}`} strokeDashoffset={-offset}
            transform="rotate(-90 90 90)" strokeLinecap="round">
            <title>{`${s.label}: ${s.value}`}</title>
          </circle>
        );
        offset += len;
        return el;
      })}
      <text x="90" y="86" textAnchor="middle" fontSize="26" fontWeight="800" fill="#ECECF4">{center}</text>
      {sub && <text x="90" y="108" textAnchor="middle" fontSize="11" fill="#A9A8C3">{sub}</text>}
    </svg>
  );
}

export function SegmentBar({ segments }: { segments: Array<{ label: string; value: number; color: string }> }) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  return (
    <div className="flex h-3.5 w-full rounded-full overflow-hidden bg-base-deep shadow-neu-in" role="img"
      aria-label={segments.map((s) => `${s.label} ${Math.round((s.value / total) * 100)}%`).join(", ")}>
      {segments.filter((s) => s.value > 0).map((s) => (
        <div key={s.label} style={{ width: `${(s.value / total) * 100}%`, background: s.color }} title={s.label} />
      ))}
    </div>
  );
}

export function BarList({ rows, format, color = C.accent }: {
  rows: Array<{ label: string; value: number; hint?: string }>; format: (n: number) => string; color?: string;
}) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <ul className="space-y-3.5">
      {rows.map((r) => (
        <li key={r.label}>
          <div className="flex items-baseline justify-between gap-3 text-sm mb-1.5">
            <span className="truncate">{r.label}{r.hint && <span className="text-ink-faint ml-2">{r.hint}</span>}</span>
            <span className="tabular text-ink-soft">{format(r.value)}</span>
          </div>
          <div className="h-2.5 rounded-full bg-base-deep shadow-neu-in overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${(r.value / max) * 100}%`, background: color }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function Meter({ value, color }: { value: number; color: string }) {
  return (
    <div className="h-2 w-24 rounded-full bg-base-deep shadow-neu-in overflow-hidden" aria-hidden>
      <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: color }} />
    </div>
  );
}

function niceMax(v: number): number {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const m = v / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
}
