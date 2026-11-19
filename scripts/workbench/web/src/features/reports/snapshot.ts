import type { JsonObject } from '@/types';
import { formatNumber } from '@/utils/format';

export function reportVisionCoverage(snapshot: JsonObject): string {
  return formatNumber(snapshot.vision_post_count);
}
