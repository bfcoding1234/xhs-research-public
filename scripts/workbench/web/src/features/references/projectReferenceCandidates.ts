import type { Author, Post } from '@/types';

export type ReferenceEntity = Post | Author;
export type ReferenceEntityType = 'post' | 'author';

function referenceSearchValues(entity: ReferenceEntity, entityType: ReferenceEntityType) {
  if (entityType === 'post') {
    const post = entity as Post;
    return [post.title, post.note_id, post.author_name, post.content];
  }
  const author = entity as Author;
  return [author.display_name, author.author_id, author.xhs_id, author.bio];
}

export function filterProjectReferenceCandidates(
  entities: ReferenceEntity[],
  entityType: ReferenceEntityType,
  existingEntityIds: number[],
  query: string,
) {
  const existing = new Set(existingEntityIds);
  const normalized = query.trim().toLocaleLowerCase('zh-CN');
  return entities.filter(
    (entity) =>
      !existing.has(entity.id) &&
      (!normalized ||
        referenceSearchValues(entity, entityType).some((value) =>
          String(value || '').toLocaleLowerCase('zh-CN').includes(normalized),
        )),
  );
}
