import * as LabelPrimitive from '@radix-ui/react-label'
import * as ProgressPrimitive from '@radix-ui/react-progress'
import { cva, type VariantProps } from 'class-variance-authority'
import { Loader2 } from 'lucide-react'
import { forwardRef, type HTMLAttributes, type InputHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        outline: 'text-foreground',
        pass: 'border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-400',
        fail: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-400',
        warn: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400',
        info: 'border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-400',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)
export const Badge = ({ className, variant, ...p }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) => (
  <span className={cn(badgeVariants({ variant }), className)} {...p} />
)

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, type, ...p }, ref) => (
  <input
    ref={ref}
    type={type}
    className={cn(
      'flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
      className,
    )}
    {...p}
  />
))
Input.displayName = 'Input'

export const Label = forwardRef<HTMLLabelElement, React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>>(({ className, ...p }, ref) => (
  <LabelPrimitive.Root ref={ref} className={cn('text-sm font-medium leading-none', className)} {...p} />
))
Label.displayName = 'Label'

const alertVariants = cva('relative flex w-full gap-3 rounded-lg border p-4 text-sm [&>svg]:mt-0.5 [&>svg]:size-4 [&>svg]:shrink-0', {
  variants: {
    variant: {
      default: 'bg-background',
      destructive: 'border-destructive/40 bg-destructive/5 text-destructive',
      warning: 'border-amber-500/40 bg-amber-500/5 text-amber-700 dark:text-amber-400',
      success: 'border-green-500/40 bg-green-500/5 text-green-700 dark:text-green-400',
    },
  },
  defaultVariants: { variant: 'default' },
})
export const Alert = ({ className, variant, ...p }: HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>) => (
  <div role="alert" className={cn(alertVariants({ variant }), className)} {...p} />
)

export function Progress({ value, indicatorClassName, className }: { value: number; indicatorClassName?: string; className?: string }) {
  return (
    <ProgressPrimitive.Root className={cn('relative h-2.5 w-full overflow-hidden rounded-full bg-secondary', className)} value={value}>
      <ProgressPrimitive.Indicator
        className={cn('h-full rounded-full bg-brand transition-all duration-700', indicatorClassName)}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </ProgressPrimitive.Root>
  )
}

export const Skeleton = ({ className, ...p }: HTMLAttributes<HTMLDivElement>) => (
  <div className={cn('animate-pulse rounded-md bg-muted', className)} {...p} />
)

export const Spinner = ({ className }: { className?: string }) => <Loader2 className={cn('size-4 animate-spin', className)} />

export const Separator = ({ className }: { className?: string }) => <div role="separator" className={cn('h-px w-full bg-border', className)} />
