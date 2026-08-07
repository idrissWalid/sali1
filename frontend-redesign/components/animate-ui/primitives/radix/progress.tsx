"use client";

import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";

export const Progress = ProgressPrimitive.Root;
export const ProgressIndicator = ProgressPrimitive.Indicator;
export type ProgressProps = React.ComponentProps<typeof ProgressPrimitive.Root>;
