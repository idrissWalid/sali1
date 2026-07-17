"use client";

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface Props {
  placeholders: string[];
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onSubmit: () => void;
  disabled?: boolean;
  className?: string;
}

export function PlaceholdersAndVanishInput({
  placeholders,
  value,
  onChange,
  onSubmit,
  disabled = false,
  className,
}: Props) {
  const [currentPlaceholder, setCurrentPlaceholder] = useState(0);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const startAnimation = () => {
    intervalRef.current = setInterval(() => {
      setCurrentPlaceholder((prev) => (prev + 1) % placeholders.length);
    }, 3000);
  };

  const handleVisibilityChange = () => {
    if (document.visibilityState !== "visible" && intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    } else if (document.visibilityState === "visible") {
      startAnimation();
    }
  };

  useEffect(() => {
    startAnimation();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placeholders]);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const newDataRef = useRef<{ x: number; y: number; r: number; color: string }[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const [animating, setAnimating] = useState(false);

  const draw = useCallback(() => {
    if (!inputRef.current) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    canvas.width = 800;
    canvas.height = 800;
    ctx.clearRect(0, 0, 800, 800);

    const computedStyles = getComputedStyle(inputRef.current);
    const fontSize = parseFloat(computedStyles.getPropertyValue("font-size"));
    ctx.font = `${fontSize * 2}px ${computedStyles.fontFamily}`;
    ctx.fillStyle = "#e3e3e3";
    ctx.fillText(value, 16, 40);

    const imageData = ctx.getImageData(0, 0, 800, 800);
    const pixelData = imageData.data;
    const newData: { x: number; y: number; color: [number, number, number, number] }[] = [];

    for (let t = 0; t < 800; t++) {
      const i = 4 * t * 800;
      for (let n = 0; n < 800; n++) {
        const e = i + 4 * n;
        if (pixelData[e] !== 0 && pixelData[e + 1] !== 0 && pixelData[e + 2] !== 0) {
          newData.push({ x: n, y: t, color: [pixelData[e], pixelData[e + 1], pixelData[e + 2], pixelData[e + 3]] });
        }
      }
    }

    newDataRef.current = newData.map(({ x, y, color }) => ({
      x, y, r: 1,
      color: `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${color[3]})`,
    }));
  }, [value]);

  useEffect(() => { draw(); }, [value, draw]);

  const animate = (start: number) => {
    const animateFrame = (pos: number = 0) => {
      requestAnimationFrame(() => {
        const newArr: typeof newDataRef.current = [];
        for (let i = 0; i < newDataRef.current.length; i++) {
          const current = newDataRef.current[i];
          if (current.x < pos) {
            newArr.push(current);
          } else {
            if (current.r <= 0) { current.r = 0; continue; }
            current.x += Math.random() > 0.5 ? 1 : -1;
            current.y += Math.random() > 0.5 ? 1 : -1;
            current.r -= 0.05 * Math.random();
            newArr.push(current);
          }
        }
        newDataRef.current = newArr;
        const ctx = canvasRef.current?.getContext("2d");
        if (ctx) {
          ctx.clearRect(pos, 0, 800, 800);
          newDataRef.current.forEach(({ x: n, y: i, r: s, color }) => {
            if (n > pos) {
              ctx.beginPath();
              ctx.rect(n, i, s, s);
              ctx.fillStyle = color;
              ctx.strokeStyle = color;
              ctx.stroke();
            }
          });
        }
        if (newDataRef.current.length > 0) {
          animateFrame(pos - 8);
        } else {
          setAnimating(false);
        }
      });
    };
    animateFrame(start);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !animating && !disabled) {
      e.preventDefault();
      vanishAndSubmit();
    }
  };

  const vanishAndSubmit = () => {
    if (!value.trim() || disabled) return;
    setAnimating(true);
    draw();
    const maxX = newDataRef.current.reduce(
      (prev, current) => (current.x > prev ? current.x : prev), 0
    );
    animate(maxX);
    onSubmit();
  };

  return (
    <div className={cn("relative flex h-11 min-w-0 flex-1 items-center", className)}>
      {/* Canvas for vanish particle animation */}
      <canvas
        ref={canvasRef}
        className={cn(
          "absolute pointer-events-none text-base transform scale-50 top-[20%] left-0 origin-top-left pr-4 transition-opacity duration-200",
          !animating ? "opacity-0" : "opacity-100"
        )}
      />

      {/* Actual input */}
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => { if (!animating) onChange(e); }}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        className={cn(
          "h-11 w-full bg-transparent border-none py-0 text-[15px] leading-5 outline-none transition-colors duration-200 focus:outline-none focus:ring-0",
          animating ? "text-transparent" : ""
        )}
        style={{
          color: animating ? "transparent" : "var(--text-main)",
          caretColor: "var(--accent-color)",
          border: "none",
          outline: "none",
          boxShadow: "none",
        }}
      />

      {/* Animated rotating placeholder */}
      <div className="pointer-events-none absolute inset-0 flex h-11 items-center">
        <AnimatePresence mode="wait">
          {!value && (
            <motion.p
              key={`ph-${currentPlaceholder}`}
              initial={{ y: 6, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: -10, opacity: 0 }}
              transition={{ duration: 0.22, ease: "easeOut" }}
              className="w-full select-none truncate text-[15px] leading-5"
              style={{ color: "var(--text-muted)" }}
            >
              {placeholders[currentPlaceholder]}
            </motion.p>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
