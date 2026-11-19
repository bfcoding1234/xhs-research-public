import type { ResearchType } from '@/types';

export type SourceFieldValue = string | string[] | null | undefined;

export interface ResearchFormValues {
  /** @deprecated 历史表单值，提交时忽略。 */
  collector?: string;
  name?: string;
  mode?: ResearchType;
  projectId?: number;
  topic?: string;
  keywords?: SourceFieldValue;
  projectKeywords?: SourceFieldValue;
  keywordCollectPosts?: boolean;
  keywordCollectAuthors?: boolean;
  keywordAuthorLimit?: number;
  authors?: SourceFieldValue;
  userKeywords?: SourceFieldValue;
  userDiscovery?: number;
  keywordDiscovery?: number;
  keywordDeep?: number;
  authorDiscovery?: number;
  authorDeep?: number;
  authorScopes?: Array<'basic_info' | 'posts'>;
  sort?: string;
  publishTime?: string;
  forceRefresh?: boolean;
}
