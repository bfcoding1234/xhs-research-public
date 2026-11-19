import { describe, expect, it } from 'vitest';
import { activeSettingsSection, SETTINGS_SECTIONS } from './settingsNavigation';

describe('settings navigation', () => {
  it('groups frequent task settings before advanced and system information', () => {
    expect(SETTINGS_SECTIONS.map((section) => section.key)).toEqual([
      'defaults',
      'source',
      'refresh',
      'vision',
      'report-prompts',
      'routing',
      'me',
      'service',
      'storage',
      'data-release',
    ]);
  });

  it('selects the last section that has crossed the activation line', () => {
    expect(
      activeSettingsSection(
        [
          { key: 'defaults', top: -300 },
          { key: 'source', top: 80 },
          { key: 'refresh', top: 520 },
        ],
        120,
      ),
    ).toBe('source');
  });

  it('keeps the first section active before the first card crosses the activation line', () => {
    expect(
      activeSettingsSection(
        [
          { key: 'defaults', top: 180 },
          { key: 'source', top: 620 },
        ],
        120,
      ),
    ).toBe('defaults');
  });

  it('activates the final section when the page reaches the bottom', () => {
    expect(
      activeSettingsSection(
        [
          { key: 'service', top: -120 },
          { key: 'storage', top: 360 },
        ],
        120,
        true,
      ),
    ).toBe('storage');
  });
});
