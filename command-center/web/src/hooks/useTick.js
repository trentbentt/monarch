import { useEffect, useState } from "react";

/** Re-render every `ms` so time-based UI (veto countdowns) stays live. */
export function useTick(ms = 1000) {
  const [, set] = useState(0);
  useEffect(() => {
    const id = setInterval(() => set((n) => n + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
  return Date.now();
}
