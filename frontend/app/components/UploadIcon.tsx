"use client";

import * as React from "react";
import { motion, useAnimation } from "framer-motion";

export interface UploadIconProps extends React.SVGProps<SVGSVGElement> {
  size?: number | string;
  isHovered?: boolean;
}

export function UploadIcon({ size = 24, isHovered, ...props }: UploadIconProps) {
  const controls = useAnimation();

  React.useEffect(() => {
    if (isHovered) {
      controls.start("animate");
    } else {
      controls.start("initial");
    }
  }, [isHovered, controls]);

  return (
    <motion.svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props as any}
      onMouseEnter={() => {
        if (isHovered === undefined) controls.start("animate");
      }}
      onMouseLeave={() => {
        if (isHovered === undefined) controls.start("initial");
      }}
    >
      <motion.g
        variants={{
          initial: { y: 0, transition: { duration: 0.3, ease: "easeInOut" } },
          animate: { y: -2, transition: { duration: 0.3, ease: "easeInOut" } },
        }}
        initial="initial"
        animate={controls}
      >
        <path d="M12 3v12" />
        <path d="m17 8-5-5-5 5" />
      </motion.g>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    </motion.svg>
  );
}
