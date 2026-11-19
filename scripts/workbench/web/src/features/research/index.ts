export { authorIdentity, default as AuthorCandidatePicker } from './AuthorCandidatePicker';
export {
  buildResearchConfiguration,
  canonicalAuthorProfileUrl,
  defaultResearchValues,
  getErrorMessage,
  normalizeAuthorSourceValues,
  researchValuesFromTask,
  resolveAuthorProfileUrls,
  sourceLimit,
  splitSourceValues,
  validateResearchConfiguration,
  validateSourceCounts,
} from './configuration';
export { default as CreateResearchTaskModal } from './CreateResearchTaskModal';
export type { RerunResearchModalProps } from './RerunResearchModal';
export { default as RerunResearchModal } from './RerunResearchModal';
export { default as ResearchFields } from './ResearchFields';
export type { ResearchFormValues, SourceFieldValue } from './types';
