// The identity motif: one tick per 12-day radar pass, dropped passes hatched.
// Used as the timeline track, and as a small rule elsewhere.
interface Props {
  dates: string[];
  dropped: boolean[];
  current?: number;
  height?: number;
  className?: string;
}

export function PassRuler({ dates, dropped, current, height = 28, className }: Props) {
  const n = dates.length;
  const x = (i: number) => ((i + 0.5) / n) * 100;
  return (
    <svg className={className} width="100%" height={height} viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <pattern id="pr-hatch" width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="3" stroke="var(--rule-strong)" strokeWidth="1.2" />
        </pattern>
      </defs>
      <line x1="0" x2="100" y1={height - 1} y2={height - 1} stroke="var(--rule-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      {dates.map((d, i) =>
        dropped[i] ? (
          <rect key={d} x={x(i) - 2.4} y={height * 0.25} width="4.8" height={height * 0.75 - 1} fill="url(#pr-hatch)" stroke="var(--rule-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        ) : (
          <line key={d} x1={x(i)} x2={x(i)} y1={i === current ? 0 : height * 0.4} y2={height - 1}
            stroke={i === current ? 'var(--radar)' : 'var(--ink-soft)'} strokeWidth={i === current ? 3 : 1} vectorEffect="non-scaling-stroke" />
        ),
      )}
    </svg>
  );
}
