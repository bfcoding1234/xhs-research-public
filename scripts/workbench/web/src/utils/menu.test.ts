import type { MenuDataItem } from '@ant-design/pro-components';
import { describe, expect, it } from 'vitest';
import { groupLowFrequencyMenuItems } from './menu';

describe('groupLowFrequencyMenuItems', () => {
  it('moves posts and settings into a final more submenu without changing their paths', () => {
    const menuData: MenuDataItem[] = [
      { path: '/my-projects', name: '个人' },
      { path: '/projects', name: '项目' },
      { path: '/posts', name: '帖子' },
      { path: '/authors', name: '作者' },
      { path: '/tasks', name: '任务中心' },
      { path: '/settings', name: '后台配置' },
    ];

    const grouped = groupLowFrequencyMenuItems(menuData);

    expect(grouped.map((item) => item.name)).toEqual([
      '个人',
      '作者',
      '项目',
      '任务中心',
      '更多',
    ]);
    expect(grouped.at(-1)?.children?.map((item) => [item.name, item.path])).toEqual([
      ['帖子', '/posts'],
      ['后台配置', '/settings'],
    ]);
  });
});
