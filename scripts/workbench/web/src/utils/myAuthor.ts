import type { Author } from '@/types';

export const MY_AUTHOR_ID_PATTERN = /^[0-9A-Za-z_-]{3,128}$/;

export function myAuthorOptions(authors: Author[]) {
  return authors.map((author) => ({
    value: author.id,
    label: [
      author.display_name || author.author_id,
      author.xhs_id ? `小红书号 ${author.xhs_id}` : `作者 ID ${author.author_id}`,
    ].join(' · '),
  }));
}
