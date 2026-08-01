"use client";

import { useEffect, useRef } from "react";
import { animate, useMotionValue, useTransform } from "framer-motion";

interface AnimatedNumberProps {
  value: number;
  className?: string;
}

/** Tweens between the previous and next value on change -- used by stat tiles. */
export function AnimatedNumber({ value, className }: AnimatedNumberProps) {
  const motionValue = useMotionValue(0);
  const rounded = useTransform(motionValue, (v) => Math.round(v).toLocaleString());
  const spanRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const controls = animate(motionValue, value, {
      duration: 0.7,
      ease: [0.16, 1, 0.3, 1],
    });
    return controls.stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  useEffect(() => {
    return rounded.on("change", (v) => {
      if (spanRef.current) spanRef.current.textContent = v;
    });
  }, [rounded]);

  return (
    <span ref={spanRef} className={className}>
      0
    </span>
  );
}
