// Story 6 — vertical draggable split with persisted width.
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { localGet, localSet } from "../localSetting";

const MIN_PANE_PX = 240;
const DEFAULT_LHS_PX = 480;
const STORAGE_KEY = "editor.split.lhsPx";
const STORAGE_VERSION = 1;

export default function SplitPane({ left, right }: { left: ReactNode; right: ReactNode }) {
  const [lhsPx, setLhsPx] = useState<number>(
    () => localGet<number>(STORAGE_KEY, STORAGE_VERSION, DEFAULT_LHS_PX),
  );
  const containerRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ active: boolean; startX: number; startLhs: number }>({
    active: false, startX: 0, startLhs: 0,
  });

  const clamp = useCallback((px: number) => {
    const w = containerRef.current?.clientWidth ?? window.innerWidth;
    const max = w - MIN_PANE_PX - 8;
    return Math.max(MIN_PANE_PX, Math.min(px, max));
  }, []);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    drag.current = { active: true, startX: e.clientX, startLhs: lhsPx };
    const target = e.target as Element & { setPointerCapture?: (id: number) => void };
    // jsdom doesn't implement setPointerCapture; guard so unit tests don't throw.
    target.setPointerCapture?.(e.pointerId);
    document.body.style.cursor = "col-resize";
  }, [lhsPx]);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!drag.current.active) return;
    const next = clamp(drag.current.startLhs + (e.clientX - drag.current.startX));
    if (containerRef.current) {
      containerRef.current.style.setProperty("--lhs-px", `${next}px`);
    }
  }, [clamp]);

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    if (!drag.current.active) return;
    drag.current.active = false;
    document.body.style.cursor = "";
    const current = containerRef.current?.style.getPropertyValue("--lhs-px");
    if (current) {
      const v = parseInt(current, 10);
      setLhsPx(v);
      localSet(STORAGE_KEY, STORAGE_VERSION, v);
    }
  }, []);

  const onDoubleClick = useCallback(() => {
    setLhsPx(DEFAULT_LHS_PX);
    localSet(STORAGE_KEY, STORAGE_VERSION, DEFAULT_LHS_PX);
    containerRef.current?.style.setProperty("--lhs-px", `${DEFAULT_LHS_PX}px`);
  }, []);

  // Re-clamp on window resize in case the window got narrower than 2 x min.
  useEffect(() => {
    const onResize = () => {
      const clamped = clamp(lhsPx);
      if (clamped !== lhsPx) setLhsPx(clamped);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [clamp, lhsPx]);

  return (
    <div
      ref={containerRef}
      className="editor"
      style={{ "--lhs-px": `${lhsPx}px` } as React.CSSProperties}
    >
      {left}
      <div
        className="split-sep"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onDoubleClick={onDoubleClick}
        role="separator"
        aria-orientation="vertical"
      />
      {right}
    </div>
  );
}
