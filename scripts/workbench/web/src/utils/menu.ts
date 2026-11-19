import type { MenuDataItem } from '@ant-design/pro-components';
import type { ReactNode } from 'react';

const LOW_FREQUENCY_MENU_PATHS = new Set(['/posts', '/settings']);
const PRIMARY_MENU_ORDER = new Map([
  ['/my-projects', 0],
  ['/authors', 1],
  ['/projects', 2],
  ['/tasks', 3],
]);

export function groupLowFrequencyMenuItems(
  menuData: MenuDataItem[],
  icon?: ReactNode,
): MenuDataItem[] {
  const primaryItems: MenuDataItem[] = [];
  const lowFrequencyItems: MenuDataItem[] = [];

  for (const item of menuData) {
    if (item.path && LOW_FREQUENCY_MENU_PATHS.has(item.path)) {
      lowFrequencyItems.push(item);
    } else {
      primaryItems.push(item);
    }
  }

  primaryItems.sort(
    (left, right) =>
      (PRIMARY_MENU_ORDER.get(left.path ?? '') ?? Number.MAX_SAFE_INTEGER) -
      (PRIMARY_MENU_ORDER.get(right.path ?? '') ?? Number.MAX_SAFE_INTEGER),
  );

  if (lowFrequencyItems.length === 0) return primaryItems;

  return [
    ...primaryItems,
    {
      path: '/more',
      key: '/more',
      name: '更多',
      icon,
      children: lowFrequencyItems,
    },
  ];
}
