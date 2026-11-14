// Draggable image-comparison divider (PRD 8.1), no library. Mouse and touch through Pointer Events,
// keyboard through role="slider" (left/right 5%, Home/End). The radar image is revealed with clip-path.
import { type KeyboardEvent, type PointerEvent, useRef, useState } from 'react';
import './Divider.css';

interface Props {
  leftSrc: string;
  rightSrc: string;
  leftAlt: string;
  rightAlt: string;
  leftLabel: string;
  rightLabel: string;
  sliderLabel: string;
  valueText: (pct: number) => string;
  size: number; // intrinsic pixel size of the square images
}

export function Divider({ leftSrc, rightSrc, leftAlt, rightAlt, leftLabel, rightLabel, sliderLabel, valueText, size }: Props) {
  const [pct, setPct] = useState(50);
  const box = useRef<HTMLDivElement>(null);
  const clamp = (v: number) => Math.max(0, Math.min(100, v));

  const fromPointer = (e: PointerEvent) => {
    const r = box.current!.getBoundingClientRect();
    setPct(clamp(((e.clientX - r.left) / r.width) * 100));
  };
  const onKey = (e: KeyboardEvent) => {
    const map: Record<string, number> = { ArrowLeft: pct - 5, ArrowDown: pct - 5, ArrowRight: pct + 5, ArrowUp: pct + 5, Home: 0, End: 100 };
    if (e.key in map) {
      e.preventDefault();
      setPct(clamp(map[e.key]));
    }
  };

  return (
    <div
      ref={box}
      className="divider"
      onPointerDown={(e) => { box.current!.setPointerCapture(e.pointerId); fromPointer(e); }}
      onPointerMove={(e) => { if (e.buttons) fromPointer(e); }}
    >
      {/* left = camera, full frame underneath */}
      <img src={leftSrc} alt={leftAlt} width={size} height={size} className="divider__img" draggable={false} fetchPriority="high" />
      {/* right = radar, clipped so only the part right of the divider shows */}
      <img src={rightSrc} alt={rightAlt} width={size} height={size} className="divider__img divider__img--top" draggable={false}
        style={{ clipPath: `inset(0 0 0 ${pct}%)` }} fetchPriority="high" />
      <span className="divider__tag divider__tag--left" aria-hidden="true">{leftLabel}</span>
      <span className="divider__tag divider__tag--right" aria-hidden="true">{rightLabel}</span>
      <div
        className="divider__handle"
        style={{ left: `${pct}%` }}
        role="slider"
        tabIndex={0}
        aria-label={sliderLabel}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(100 - pct)}
        aria-valuetext={valueText(Math.round(100 - pct))}
        onKeyDown={onKey}
      >
        <span className="divider__grip" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 20 20"><path d="M7 5 L2 10 L7 15 M13 5 L18 10 L13 15" fill="none" stroke="currentColor" strokeWidth="2" /></svg>
        </span>
      </div>
    </div>
  );
}
