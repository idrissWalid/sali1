"use client";

import * as React from "react";
import { motion, useAnimation, type Variants } from "motion/react";

type AnimationMap = Record<string, Record<string, Variants>>;

export type IconProps<T extends string = string> = Omit<React.ComponentProps<typeof motion.svg>, "animate"> & {
  animation?: T;
  animateOnHover?: boolean;
  size?: number | string;
};

const AnimateIconContext = React.createContext<{ controls: ReturnType<typeof useAnimation> } | null>(null);

export function useAnimateIconContext() {
  const context = React.useContext(AnimateIconContext);
  if (!context) throw new Error("Animated icons must be rendered inside IconWrapper.");
  return context;
}

export function getVariants<T extends AnimationMap>(animations: T) {
  return animations.default;
}

export function IconWrapper<T extends string>({ icon: Icon, animateOnHover = false, ...props }: IconProps<T> & { icon: React.ComponentType<IconProps<T>> }) {
  const controls = useAnimation();
  return (
    <AnimateIconContext.Provider value={{ controls }}>
      <Icon {...(props as IconProps<T>)}
        onMouseEnter={() => { if (animateOnHover) void controls.start("animate"); }}
        onMouseLeave={() => { if (animateOnHover) void controls.start("initial"); }} />
    </AnimateIconContext.Provider>
  );
}
