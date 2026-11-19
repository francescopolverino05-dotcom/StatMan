export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" fill="none" aria-hidden="true" className={className}>
      <rect x="4" y="8" width="40" height="32" rx="2" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="24" cy="24" r="6" stroke="currentColor" strokeWidth="1.2" />
      <path d="M24 8v32" stroke="currentColor" strokeWidth="1.2" strokeLinecap="square" />
      <path d="M4 14h8v20H4M36 14h8v20h-8" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}
