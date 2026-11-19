import { describe, expect, it } from 'vitest';
import type { Project, Task, TaskStatus, TaskType } from '@/types';
import {
  buildProjectTaskRows,
  canDeleteProject,
  countActiveProjectTasks,
  filterProjectTaskRows,
  isProjectTaskStateUnknown,
} from './projectTasks';

function project(id: number): Project {
  return {
    id,
    name: `项目 ${id}`,
    slug: `project-${id}`,
    description: '',
    research_type: 'mixed',
    status: 'active',
    config_json: {},
    latest_report_id: null,
    created_at: '',
    updated_at: '',
    archived_at: null,
  };
}

function task(id: string, projectId: number, status: TaskStatus, taskType: TaskType): Task {
  return {
    id,
    project_id: projectId,
    task_type: taskType,
    mode: 'mixed',
    created_from: 'web',
    input_json: {},
    status,
    current_phase: status,
    progress_current: 0,
    progress_total: 0,
    warning_count: 0,
    error_message: '',
    result_json: {},
    created_at: '',
    started_at: null,
    finished_at: null,
  };
}

describe('project task aggregation', () => {
  it('keeps every active task for a project and counts tasks rather than projects', () => {
    const rows = buildProjectTaskRows(
      [project(1), project(2)],
      [
        task('report', 1, 'running', 'ai_report'),
        task('vision', 1, 'queued', 'vision'),
        task('done', 1, 'completed', 'research'),
        task('login', 2, 'waiting_login', 'research'),
      ],
    );

    expect(rows[0]?.active_tasks.map((value) => value.id)).toEqual(['report', 'vision']);
    expect(rows[1]?.active_tasks.map((value) => value.id)).toEqual(['login']);
    expect(countActiveProjectTasks(rows)).toBe(3);
  });

  it('matches a status found on any active task', () => {
    const rows = buildProjectTaskRows(
      [project(1), project(2)],
      [
        task('running-first', 1, 'running', 'ai_report'),
        task('queued-second', 1, 'queued', 'vision'),
        task('running-only', 2, 'running', 'research'),
      ],
    );

    expect(filterProjectTaskRows(rows, { task_status: 'queued' }).map((value) => value.id)).toEqual([
      1,
    ]);
    expect(filterProjectTaskRows(rows, { task_status: 'running' }).map((value) => value.id)).toEqual([
      1, 2,
    ]);
  });

  it('blocks project deletion while task state is loading or failed', () => {
    expect(isProjectTaskStateUnknown({ isPending: true, isError: false })).toBe(true);
    expect(isProjectTaskStateUnknown({ isPending: false, isError: true })).toBe(true);
    expect(
      canDeleteProject({
        taskStateUnknown: true,
        activeTaskCount: 0,
        confirmationMatches: true,
      }),
    ).toBe(false);
    expect(
      canDeleteProject({
        taskStateUnknown: false,
        activeTaskCount: 0,
        confirmationMatches: true,
      }),
    ).toBe(true);
  });
});
