"use client";
import { useState, useEffect } from "react";

interface Props {
  src: string | null;
  onClose: () => void;
}

export default function ImageLightbox({ src, onClose }: Props) {
  const [scale, setScale] = useState(1);
  const [isDragging, setIsDragging] = useState(false);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  const [prevSrc, setPrevSrc] = useState<string | null>(src);
  if (src !== prevSrc) {
    setScale(1);
    setPosition({ x: 0, y: 0 });
    setPrevSrc(src);
  }

  // Handle escape key to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (src) window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [src, onClose]);

  if (!src) return null;

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const zoomSensitivity = 0.1;
    const delta = e.deltaY > 0 ? -1 : 1;
    let newScale = scale + delta * zoomSensitivity;
    newScale = Math.max(0.5, Math.min(newScale, 5)); // Limit zoom between 0.5x and 5x
    setScale(newScale);
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true);
    setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isDragging) {
      setPosition({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: "rgba(0, 0, 0, 0.85)",
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
      }}
      onWheel={handleWheel}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onMouseMove={handleMouseMove}
    >
      {/* Bouton de fermeture */}
      <button
        onClick={onClose}
        style={{
          position: "absolute",
          top: "20px",
          right: "20px",
          background: "rgba(255,255,255,0.1)",
          border: "none",
          color: "white",
          fontSize: "24px",
          width: "40px",
          height: "40px",
          borderRadius: "50%",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          zIndex: 10000,
          transition: "background 0.2s",
        }}
        onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.2)"}
        onMouseLeave={e => e.currentTarget.style.background = "rgba(255,255,255,0.1)"}
      >
        ×
      </button>

      {/* Contrôles de zoom */}
      <div style={{
        position: "absolute",
        bottom: "30px",
        display: "flex",
        gap: "10px",
        background: "rgba(0,0,0,0.5)",
        padding: "8px 16px",
        borderRadius: "24px",
        zIndex: 10000,
      }}>
        <button
          onClick={() => setScale(Math.max(0.5, scale - 0.2))}
          style={{ background: "transparent", border: "none", color: "white", cursor: "pointer", fontSize: "20px" }}
        >−</button>
        <span style={{ color: "white", display: "flex", alignItems: "center", minWidth: "50px", justifyContent: "center", fontSize: "14px", fontFamily: "monospace" }}>
          {Math.round(scale * 100)}%
        </span>
        <button
          onClick={() => setScale(Math.min(5, scale + 0.2))}
          style={{ background: "transparent", border: "none", color: "white", cursor: "pointer", fontSize: "20px" }}
        >+</button>
        <button
          onClick={() => { setScale(1); setPosition({ x: 0, y: 0 }); }}
          style={{ background: "transparent", border: "none", color: "rgba(255,255,255,0.6)", cursor: "pointer", fontSize: "14px", marginLeft: "10px" }}
        >RÉINITIALISER</button>
      </div>

      {/* Image */}
      <img
        src={src}
        alt="En grand"
        onMouseDown={handleMouseDown}
        onDragStart={e => e.preventDefault()} // Empêche le comportement drag par défaut du navigateur
        style={{
          transform: `translate(${position.x}px, ${position.y}px) scale(${scale})`,
          transition: isDragging ? "none" : "transform 0.1s ease-out",
          cursor: isDragging ? "grabbing" : "grab",
          maxWidth: "90vw",
          maxHeight: "90vh",
          objectFit: "contain",
          boxShadow: "0 10px 40px rgba(0,0,0,0.5)",
          borderRadius: "8px",
        }}
      />
    </div>
  );
}
