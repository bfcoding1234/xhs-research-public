export type AuthorPostDetailBase = 'authors' | 'my-projects';

export type PostDetailNavigation =
  | { source: 'global' }
  | { source: 'project'; projectId: number }
  | { source: 'author'; authorId: number; base?: AuthorPostDetailBase };

function validId(value: string | null): number | undefined {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

export function buildPostDetailPath(postId: number, navigation: PostDetailNavigation): string {
  const params = new URLSearchParams();

  if (navigation.source === 'project') {
    params.set('from', 'project');
    params.set('project_id', String(navigation.projectId));
  } else if (navigation.source === 'author') {
    params.set('from', 'author');
    params.set('author_id', String(navigation.authorId));
    if (navigation.base === 'my-projects') params.set('base', navigation.base);
  }

  const query = params.toString();
  return `/posts/${postId}${query ? `?${query}` : ''}`;
}

export function parsePostDetailNavigation(search: string): PostDetailNavigation {
  const params = new URLSearchParams(search);
  const source = params.get('from');

  if (source === 'project') {
    const projectId = validId(params.get('project_id'));
    if (projectId) return { source, projectId };
  }

  if (source === 'author') {
    const authorId = validId(params.get('author_id'));
    if (authorId) {
      return {
        source,
        authorId,
        base: params.get('base') === 'my-projects' ? 'my-projects' : 'authors',
      };
    }
  }

  return { source: 'global' };
}

export function postDetailReturnPath(navigation: PostDetailNavigation): string {
  if (navigation.source === 'project') return `/projects/${navigation.projectId}/posts`;
  if (navigation.source === 'author') {
    const base = navigation.base === 'my-projects' ? '/my-projects' : `/authors/${navigation.authorId}`;
    return `${base}/posts`;
  }
  return '/posts';
}

export function postDetailMenuPath(search: string): string | undefined {
  const navigation = parsePostDetailNavigation(search);
  if (navigation.source === 'project') return `/projects/${navigation.projectId}/posts`;
  if (navigation.source === 'author') {
    return navigation.base === 'my-projects'
      ? '/my-projects/posts'
      : `/authors/${navigation.authorId}/posts`;
  }
  return undefined;
}
