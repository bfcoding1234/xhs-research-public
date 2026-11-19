import type { JsonObject, Project } from '@/types';

export const MY_PROJECT_KIND = 'my_project';

export interface MyProjectMetadata extends JsonObject {
  project_kind: typeof MY_PROJECT_KIND;
}

export function isMyProject(project: Pick<Project, 'config_json'>): boolean {
  return project.config_json?.project_kind === MY_PROJECT_KIND;
}

export function buildMyProjectMetadata(): MyProjectMetadata {
  return { project_kind: MY_PROJECT_KIND };
}

export function findMyProject(projects: Project[]): Project | undefined {
  return projects.find(isMyProject);
}
