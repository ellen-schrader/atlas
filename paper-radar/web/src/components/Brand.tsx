import { Compass } from "lucide-react";

export function Brand({ size = 20 }: { size?: number }) {
  return (
    <div className="flex items-center gap-2 font-semibold tracking-tight text-fg">
      <Compass size={size} className="text-accent" />
      <span style={{ fontSize: size * 0.9 }}>Atlas</span>
    </div>
  );
}
