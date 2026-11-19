import { describe, expect, it } from 'vitest';
import { projectFinalSyncQueryKeys, queryKeys } from './queryKeys';

describe('project final sync query keys', () => {
  it('keeps the image model catalog under the settings cache namespace', () => {
    expect(queryKeys.visionModels).toEqual(['settings', 'vision-models']);
  });

  it('refreshes each project resource exactly once after an active task settles', () => {
    expect(projectFinalSyncQueryKeys(12)).toEqual([
      ['project', '12'],
      ['project', '12', 'keywords'],
      ['project', '12', 'posts'],
      ['project', '12', 'post-coverage'],
      ['project', '12', 'authors'],
      ['project', '12', 'reports'],
      ['project', '12', 'vision'],
      ['project', '12', 'report-status'],
      ['project', '12', 'tasks'],
    ]);
  });
});
