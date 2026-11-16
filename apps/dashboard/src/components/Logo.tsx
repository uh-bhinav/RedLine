/** RedLine "RL" logomark (SVG). `size` in px. */
export function Logo({ className, size = 28 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="8" fill="hsl(var(--brand))" />
      <path
        d="M8 22V10h7a4 4 0 0 1 0 8h-7m6 0 5 4"
        fill="none"
        stroke="#fff"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
