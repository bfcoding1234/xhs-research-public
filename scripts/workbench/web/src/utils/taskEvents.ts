import type { JsonObject } from '@/types';

export function taskEventWarnings(payload: JsonObject): string[] {
  const warnings = payload.warnings;
  if (!Array.isArray(warnings)) return [];
  return [
    ...new Set(
      warnings
        .map((warning) => {
          if (typeof warning === 'string') return warning.trim();
          if (warning && typeof warning === 'object') {
            const value = warning as Record<string, unknown>;
            return String(value.message ?? value.error ?? '').trim();
          }
          return '';
        })
        .filter(Boolean),
    ),
  ];
}
