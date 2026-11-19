export const DEFAULT_DEEP_RANGE_ERROR = '深度分析数量不能大于发现数量';

export function defaultDeepFitsDiscovery(deep: number, discovery: number): boolean {
  return Number(deep) <= Number(discovery);
}
