export type LoginLimitOptions = {
  limit?: number;
  windowMs?: number;
  maxKeys?: number;
  now?: () => number;
};

export type LoginLimitResult = {
  allowed: boolean;
  retryAfter: number;
};

export function createLoginLimiter(options: LoginLimitOptions = {}) {
  const limit = options.limit ?? 5;
  const windowMs = options.windowMs ?? 60_000;
  const maxKeys = options.maxKeys ?? 10_000;
  const now = options.now ?? Date.now;
  const hits = new Map<string, number[]>();

  return {
    allow(key: string): LoginLimitResult {
      const current = now();
      const cutoff = current - windowMs;
      const values = (hits.get(key) ?? []).filter((stamp) => stamp > cutoff);
      if (values.length >= limit) {
        hits.delete(key);
        hits.set(key, values);
        return {
          allowed: false,
          retryAfter: Math.max(
            1,
            Math.ceil((values[0] + windowMs - current) / 1000),
          ),
        };
      }
      values.push(current);
      hits.delete(key);
      hits.set(key, values);
      while (hits.size > maxKeys) {
        const oldest = hits.keys().next().value;
        if (oldest === undefined) break;
        hits.delete(oldest);
      }
      return { allowed: true, retryAfter: 0 };
    },
    size: () => hits.size,
  };
}
