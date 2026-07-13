/**
 * The Atlas mark: a field of points inside a map hull. It reads as a cluster of
 * papers and as a cluster of cells at once — which is the product — and it's what
 * the app literally draws on the Overview. Replaces the stock lucide compass.
 */
export function AtlasMark({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      {/* the hull — a map sheet, folded */}
      <path
        d="M16 3.2 27.4 10v12L16 28.8 4.6 22V10z"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.4}
        strokeLinejoin="round"
        opacity={0.38}
      />
      {/* the field — papers, cells */}
      <g fill="currentColor">
        <circle cx="16" cy="9.4" r="2.3" />
        <circle cx="10.6" cy="15" r="1.5" />
        <circle cx="21.6" cy="14.2" r="1.7" />
        <circle cx="13.4" cy="20.6" r="1.3" />
        <circle cx="20" cy="21" r="1.1" />
        <circle cx="16.2" cy="15.6" r="1" />
      </g>
    </svg>
  );
}

export function Brand({ size = 20 }: { size?: number }) {
  return (
    <div className="flex items-center gap-2 text-fg">
      <AtlasMark size={size} className="text-accent" />
      <span className="font-serif font-semibold tracking-tight" style={{ fontSize: size * 0.95 }}>
        Atlas
      </span>
    </div>
  );
}
