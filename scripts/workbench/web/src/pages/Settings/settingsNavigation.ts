export type SettingsSectionKey =
  | 'defaults'
  | 'source'
  | 'refresh'
  | 'vision'
  | 'report-prompts'
  | 'routing'
  | 'me'
  | 'service'
  | 'storage'
  | 'data-release';

export const SETTINGS_SECTION_GROUPS: Array<{
  key: string;
  label: string;
  description: string;
  sections: Array<{ key: SettingsSectionKey; label: string }>;
}> = [
  {
    key: 'research',
    label: '调研与采集',
    description: '控制新任务的默认规模、来源边界与数据刷新节奏。',
    sections: [
      { key: 'defaults', label: '调研默认值' },
      { key: 'source', label: '来源保护' },
      { key: 'refresh', label: '刷新策略' },
    ],
  },
  {
    key: 'processing',
    label: '能力与处理',
    description: '管理图片理解、报告提示词，以及业务能力调用采集指令的优先顺序。',
    sections: [
      { key: 'vision', label: '图片理解' },
      { key: 'report-prompts', label: '报告提示词' },
      { key: 'routing', label: '能力路由' },
    ],
  },
  {
    key: 'identity',
    label: '个人设置',
    description: '指定“个人”入口所代表的作者身份。',
    sections: [{ key: 'me', label: '个人作者' }],
  },
  {
    key: 'system',
    label: '系统信息',
    description: '查看本地服务能力、执行资源和数据存储概况。',
    sections: [
      { key: 'service', label: '服务状态' },
      { key: 'storage', label: '存储概况' },
      { key: 'data-release', label: '发布到线上' },
    ],
  },
];

export const SETTINGS_SECTIONS = SETTINGS_SECTION_GROUPS.flatMap((group) => group.sections);

export function activeSettingsSection(
  positions: Array<{ key: SettingsSectionKey; top: number }>,
  activationOffset: number,
  reachedPageEnd = false,
): SettingsSectionKey | undefined {
  if (reachedPageEnd) return positions.at(-1)?.key;
  let active = positions[0]?.key;
  for (const position of positions) {
    if (position.top > activationOffset) break;
    active = position.key;
  }
  return active;
}
