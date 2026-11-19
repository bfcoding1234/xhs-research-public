import type { Task, TaskStatus } from '@/types';
import { activeTaskStatuses } from './format';

export function activeTaskIds(
  tasks: readonly Pick<Task, 'id' | 'status'>[],
): ReadonlySet<string> {
  return new Set(
    tasks.filter((task) => activeTaskStatuses.has(task.status)).map((task) => task.id),
  );
}

export function didActiveTaskSettle(
  previous: ReadonlySet<string> | undefined,
  current: ReadonlySet<string>,
): boolean {
  if (!previous) return false;
  return Array.from(previous).some((taskId) => !current.has(taskId));
}

export function didTaskSettle(
  previous: TaskStatus | undefined,
  current: TaskStatus,
): boolean {
  return Boolean(
    previous && activeTaskStatuses.has(previous) && !activeTaskStatuses.has(current),
  );
}
