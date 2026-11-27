'use client';

import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { CheckCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

const checkCircleVariants = cva(
  'inline-flex items-center justify-center',
  {
    variants: {
      size: {
        default: 'h-4 w-4',
        sm: 'h-3 w-3',
        lg: 'h-5 w-5',
      },
    },
    defaultVariants: {
      size: 'default',
    },
  }
);

export interface CheckCircleProps
  extends React.SVGAttributes<SVGSVGElement>,
    VariantProps<typeof checkCircleVariants> {}

function CheckCircleIcon({ className, size = 'default', ...props }: CheckCircleProps) {
  return <CheckCircle className={cn(checkCircleVariants({ size }), className)} {...props} />;
}

export { CheckCircleIcon };