import * as React from 'react';

import {
  Progress as ProgressPrimitive,
  ProgressIndicator as ProgressIndicatorPrimitive,
  type ProgressProps as ProgressPrimitiveProps,
} from '@/components/animate-ui/primitives/radix/progress';
import { cn } from '@/lib/utils';

type ProgressProps = ProgressPrimitiveProps;

function Progress({ className, value, ...props }: ProgressProps & { value?: number }) {
  return (
    <ProgressPrimitive
      className={cn(
        'relative h-2 w-full overflow-hidden rounded-full bg-[var(--border-color)]',
        className,
      )}
      {...props}
    >
      <ProgressIndicatorPrimitive 
        className="h-full w-full flex-1 rounded-full bg-[var(--accent-color)] transition-all duration-500 ease-in-out" 
        style={{ transform: `translateX(-${100 - (value || 0)}%)` }}
      />
    </ProgressPrimitive>
  );
}

export { Progress, type ProgressProps };
