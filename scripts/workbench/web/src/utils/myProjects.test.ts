import { describe, expect, it } from 'vitest';
import type { Project } from '@/types';
import { buildMyProjectMetadata, findMyProject, isMyProject } from './myProjects';

function project(id: number, config_json: Project['config_json']): Project {
  return {
    id,
    name: `项目 ${id}`,
    slug: `project-${id}`,
    description: '',
    research_type: 'author',
    status: 'active',
    config_json,
    latest_report_id: null,
    created_at: '',
    updated_at: '',
    archived_at: null,
  };
}

describe('my project singleton metadata', () => {
  it('marks and finds the one my project', () => {
    const ordinary = project(1, {});
    const mine = project(2, buildMyProjectMetadata());

    expect(isMyProject(ordinary)).toBe(false);
    expect(isMyProject(mine)).toBe(true);
    expect(findMyProject([ordinary, mine])).toBe(mine);
  });
});
