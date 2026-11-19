import type { Project, ResearchType, Task, TaskStatus } from '@/types';
import { activeTaskStatuses } from './format';

export interface ProjectTaskRow extends Project {
  task_status?: TaskStatus;
  active_tasks: Task[];
}

export type ProjectTaskStatusFilter = Exclude<TaskStatus, 'cancelled'> | 'not_started';

export interface ProjectTaskFilters {
  name?: string;
  research_type?: ResearchType;
  task_status?: ProjectTaskStatusFilter;
}

export function isProjectTaskStateUnknown(state: {
  isPending: boolean;
  isError: boolean;
}): boolean {
  return state.isPending || state.isError;
}

export function canDeleteProject(input: {
  taskStateUnknown: boolean;
  activeTaskCount: number;
  confirmationMatches: boolean;
}): boolean {
  return !input.taskStateUnknown && input.activeTaskCount === 0 && input.confirmationMatches;
}

export function buildProjectTaskRows(projects: Project[], tasks: Task[]): ProjectTaskRow[] {
  const tasksByProject = new Map<number, Task[]>();
  for (const task of tasks) {
    if (task.project_id === null) {
      continue;
    }
    const projectTasks = tasksByProject.get(task.project_id) ?? [];
    projectTasks.push(task);
    tasksByProject.set(task.project_id, projectTasks);
  }

  return projects.map((project) => {
    const projectTasks = tasksByProject.get(project.id) ?? [];
    const activeTasks = projectTasks.filter((task) => activeTaskStatuses.has(task.status));
    return {
      ...project,
      active_tasks: activeTasks,
      task_status: activeTasks[0]?.status ?? projectTasks[0]?.status ?? project.latest_task_status,
    };
  });
}

export function countActiveProjectTasks(rows: ProjectTaskRow[]): number {
  return rows.reduce((total, project) => total + project.active_tasks.length, 0);
}

export function filterProjectTaskRows(
  rows: ProjectTaskRow[],
  filters: ProjectTaskFilters,
): ProjectTaskRow[] {
  const name = filters.name?.trim().toLocaleLowerCase('zh-CN');
  return rows.filter((project) => {
    const matchesName =
      !name ||
      project.name.toLocaleLowerCase('zh-CN').includes(name) ||
      project.description?.toLocaleLowerCase('zh-CN').includes(name);
    const matchesType =
      !filters.research_type || project.research_type === filters.research_type;
    const matchesStatus =
      !filters.task_status ||
      (filters.task_status === 'not_started'
        ? !project.task_status
        : project.active_tasks.some((task) => task.status === filters.task_status) ||
          (project.active_tasks.length === 0 && project.task_status === filters.task_status));
    return matchesName && matchesType && matchesStatus;
  });
}
