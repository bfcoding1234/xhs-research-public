export type ResearchType = 'keyword' | 'author' | 'mixed';
export type TaskType = 'research' | 'vision' | 'ai_report' | 'keyword_suggestions' | 'comments';
export type TaskMode = ResearchType | 'post';
export type TaskStatus =
  | 'queued'
  | 'running'
  | 'waiting_login'
  | 'completed'
  | 'partial'
  | 'failed'
  | 'cancelled';

export type JsonObject = Record<string, unknown>;

export interface Health {
  status: 'ok';
  version: string;
  data_dir: string;
  routing_mode: 'capability';
  collectors: string[];
  capability_routes: CapabilityRoute[];
  ai_capabilities?: {
    keyword_suggestions: boolean;
  };
}

export interface Stats {
  projects: number;
  global_posts: number;
  global_authors: number;
  tasks: number;
  reports: number;
  media_assets: number;
  downloaded_media: number;
  vision_analyses: number;
  database_bytes: number;
  media_bytes: number;
}

export interface DataReleasePreview {
  enabled: boolean;
  source_data_dir: string;
  target_data_dir: string;
  target_online: boolean;
  target_version: string;
  source_counts: Record<string, number>;
  target_counts: Record<string, number>;
  source_active_tasks: Array<{ id: string; status: string; task_type: string; current_phase: string }>;
  target_active_tasks: Array<{ id: string; status: string; task_type: string; current_phase: string }>;
  can_publish: boolean;
  rules: string[];
}

export interface DataRelease {
  id: string;
  status: 'completed' | 'failed';
  summary_json: JsonObject;
  created_at: string;
  completed_at: string | null;
  error_message: string;
}

export interface DataReleaseResult {
  status: 'completed';
  release_id: string;
  changed: Record<string, number>;
  media: Record<string, number>;
}

export interface Project {
  id: number;
  name: string;
  slug: string;
  description: string;
  research_type: ResearchType;
  status: string;
  config_json: JsonObject;
  latest_report_id: number | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  post_count?: number;
  author_count?: number;
  keyword_count?: number;
  report_count?: number;
  latest_task_status?: TaskStatus;
}

export interface ProjectKeyword {
  id: number;
  project_id: number;
  keyword: string;
  source: ProjectKeywordSource | string;
  created_at: string;
  updated_at: string;
}

export type ProjectKeywordSource = 'manual' | 'ai_generated';

export interface KeywordSuggestion {
  keyword: string;
  category: string;
  reason: string;
}

export interface KeywordSuggestionsResponse {
  request_id: string;
  keywords: KeywordSuggestion[];
  model?: string;
  prompt_version?: string;
  reference_sources: ProjectKeywordSource[];
}

export interface KeywordSuggestionTaskResult {
  keyword_suggestions?: KeywordSuggestionsResponse;
}

export type PostSort =
  | 'default'
  | 'title_asc'
  | 'title_desc'
  | 'likes_asc'
  | 'likes_desc'
  | 'favorites_asc'
  | 'favorites_desc'
  | 'comments_asc'
  | 'comments_desc'
  | 'published_asc'
  | 'published_desc'
  | 'updated_asc'
  | 'updated_desc'
  | 'popularity_asc'
  | 'popularity_desc'
  | 'attention_asc'
  | 'attention_desc'
  | 'project_count_asc'
  | 'project_count_desc';

export type OcrStatus = 'pending' | 'completed' | 'other';
export type ImageScope = 'cover' | 'detail';
export type MediaStorageFilter = 'all' | 'remote' | 'local' | 'none';
export type MediaStorageStatus = Exclude<MediaStorageFilter, 'all'>;

export interface ProjectPostQuery {
  page: number;
  page_size: number;
  query: string;
  type: 'all' | 'image' | 'video';
  detail: 'all' | 'preview' | 'detailed';
  ocr: 'all' | OcrStatus;
  vision: 'all' | 'yes' | 'no';
  media_storage: MediaStorageFilter;
  popularity: string;
  sort: PostSort;
}

export interface PostQuery {
  page: number;
  page_size: number;
  query: string;
  type: 'all' | 'image' | 'video';
  detail: 'all' | 'preview' | 'detailed';
  ocr: 'all' | OcrStatus;
  vision: 'all' | 'yes' | 'no';
  sort: ProjectPostQuery['sort'];
  exclude_project_id?: number;
}

export interface ProjectPostPage {
  items: Post[];
  total: number;
  page: number;
  page_size: number;
}

export interface ProjectPostCoverage {
  total: number;
  detailed: number;
  preview: number;
  ocr_available: number;
  ocr_completed: number;
  ocr_pending: number;
  ocr_other: number;
}

export type PostPage = ProjectPostPage;

export interface ProjectReferenceIds {
  post_ids: number[];
  author_ids: number[];
}

export interface EntityProjectReference {
  id: number;
  name: string;
  slug: string;
  relation_type?: string;
}

export interface ProjectReferenceResult {
  project_id: number;
  post_ids: number[];
  author_ids: number[];
  added_post_count: number;
  added_author_count: number;
  post_count: number;
  author_count: number;
}

export interface ProjectReferenceRemovalResult {
  project_id: number;
  post_ids: number[];
  author_ids: number[];
  removed_post_count: number;
  removed_author_count: number;
  post_count: number;
  author_count: number;
}

export interface ProjectAuthorPostConflict {
  code: 'author_has_project_posts';
  error: string;
  authors: Array<{
    id: number;
    name: string;
    project_post_count: number;
  }>;
  total_post_count: number;
}

export interface ResearchSource {
  profile_urls: string[];
  author_ids?: string[];
  keywords: string[];
  user_keywords?: string[];
  filters: { sort?: string; publish_time?: string };
}

export interface AuthorCollectionConfiguration {
  scopes: Array<'basic_info' | 'posts'>;
}

export interface ResearchLimits {
  discovery: number;
  deep: number;
}

export interface VisionConfiguration {
  processing_method?: 'vision' | 'ocr';
  image_scopes: ImageScope[];
  mode: 'vision-selective' | 'vision-all';
  vision_ratio: number;
  vision_count: number;
  vision_max_count: number;
  vision_batch_size: number;
}

export type VisionTaskConfiguration = Pick<
  VisionConfiguration,
  'processing_method' | 'image_scopes' | 'mode' | 'vision_batch_size'
> &
  Partial<Pick<VisionConfiguration, 'vision_ratio' | 'vision_count' | 'vision_max_count'>>;

export interface ResearchConfiguration {
  /** @deprecated 历史任务字段；新任务由原子能力路由执行。 */
  collector?: string;
  topic: string;
  source: ResearchSource;
  limits: ResearchLimits;
  keyword_limits: ResearchLimits;
  author_limits: ResearchLimits;
  user_limits?: { discovery: number };
  author_collection?: AuthorCollectionConfiguration;
  image_analysis: { mode: 'ocr-only'; vision_ratio: 0; vision_count: 0 };
  force_refresh: boolean;
  author_update?: {
    scopes: Array<'basic_info' | 'preview_posts' | 'detailed_posts'>;
  };
}

export type TaskInputJson = JsonObject &
  Partial<Omit<ResearchConfiguration, 'image_analysis'>> & {
    image_analysis?: unknown;
    vision_scope?: unknown;
    operation?: unknown;
    report_generation?: unknown;
    report_scope?: unknown;
    author_update_bulk?: unknown;
    post_detail_update?: unknown;
    keyword_suggestions?: unknown;
    post_comments?: unknown;
    post_snapshot?: unknown;
  };

export interface Task {
  id: string;
  project_id: number | null;
  author_id?: number | null;
  post_id?: number | null;
  task_type: TaskType;
  mode: TaskMode;
  created_from: string;
  input_json: TaskInputJson;
  status: TaskStatus;
  current_phase: string;
  progress_current: number;
  progress_total: number;
  warning_count: number;
  error_message: string;
  result_json: JsonObject;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface TaskReceipt {
  id: string;
  status: 'queued';
  url: string;
}

export interface MyAuthorSetupResult {
  author_id: number;
  task: TaskReceipt | null;
}

export interface DeleteProjectResult {
  deleted_project_id: number;
  name: string;
  deleted_tasks: number;
  detached_tasks?: number;
  deleted_project_posts: number;
  deleted_project_authors: number;
  deleted_reports: number;
  global_entities_preserved: boolean;
}

export interface TaskEvent {
  id: number;
  task_id: string;
  phase: string;
  event_type: string;
  payload_json: JsonObject & { message?: string };
  created_at: string;
}

export interface MediaAsset {
  id: number;
  post_id: number;
  media_index: number;
  media_type: string;
  original_url: string;
  local_path: string;
  local_url?: string;
  ocr_text: string;
  ocr_engine: string;
  download_status: string;
  updated_at: string;
}

export interface VisionAnalysis {
  id: number;
  post_id: number;
  model: string;
  prompt_version: string;
  analysis_json: {
    cover_hook?: string;
    visual_style?: string;
    layout?: string;
    information_density?: string;
    credibility_signals?: string[];
    emotion?: string;
    suitable_audience?: string[];
    reusable_patterns?: string[];
    problems?: string[];
    [key: string]: unknown;
  };
  analyzed_at: string;
}

export interface Post {
  id: number;
  note_id: string;
  author_id: number;
  author_name: string;
  external_author_id: string;
  title: string;
  content: string;
  note_type: string;
  note_url: string;
  cover_url: string;
  cover_local_path: string;
  media_local_path?: string;
  media_url?: string;
  media_remote_url?: string;
  publish_date: string;
  likes_count: number | null;
  favorites_count: number | null;
  comments_count: number | null;
  author_followers_count?: number | null;
  attention_score?: number | null;
  detail_level: string;
  popularity_score?: number;
  popularity_percentile?: number;
  popularity_level?: string;
  popularity_method?: string;
  has_ocr_result?: number;
  ocr_status?: OcrStatus;
  has_vision_result?: number;
  sources?: string;
  updated_at: string;
  last_seen_at: string;
  last_detail_fetched_at?: string | null;
  last_comments_fetched_at?: string | null;
  media?: MediaAsset[];
  media_storage_status?: MediaStorageStatus;
  vision?: VisionAnalysis[];
  project_count?: number;
  projects?: EntityProjectReference[];
}

export interface AuthorPost {
  id: number;
  note_id: string;
  title: string;
  note_url: string;
  cover_url: string;
  cover_local_path: string;
  likes_count: number | null;
  publish_date: string;
  detail_level: string;
  has_ocr_result?: number;
  ocr_status?: OcrStatus;
  has_vision_result?: number;
  note_type?: string;
  media_url?: string;
  media_remote_url?: string;
  favorites_count?: number | null;
  comments_count?: number | null;
  updated_at?: string;
  last_detail_fetched_at?: string | null;
  media_storage_status?: MediaStorageStatus;
}

export interface Author {
  id: number;
  author_id: string;
  xhs_id: string;
  display_name: string;
  profile_url: string;
  bio: string;
  ip_location: string;
  followers_count: number | null;
  following_count: number | null;
  likes_collections_count: number | null;
  avatar_url: string;
  avatar_local_path: string;
  avatar_local_url?: string;
  relation_type?: string;
  project_post_count?: number;
  hot_post_count?: number;
  peak_popularity_percentile?: number;
  selection_priority?: number;
  post_count?: number;
  stored_post_count?: number;
  total_post_count?: number | null;
  project_count?: number;
  first_seen_at: string;
  last_seen_at: string;
  last_profile_fetched_at: string | null;
  updated_at: string;
  posts?: AuthorPost[];
  projects?: EntityProjectReference[];
}

export interface Report {
  id: number;
  project_id: number | null;
  author_id?: number;
  task_id: string | null;
  version: number;
  report_type: string;
  status: 'generating' | 'completed' | 'partial';
  title: string;
  summary_json: JsonObject;
  content_markdown: string;
  evidence_post_count: number;
  evidence_author_count: number;
  generated_at: string;
  generator_type: string;
  generator_version: number;
  model: string;
  prompt_version: string;
  evidence_snapshot_json: JsonObject;
  generation_config_json: JsonObject;
}

export interface DataSummaryDistribution {
  count: number;
  average: number | null;
  median: number | null;
  p75: number | null;
  p90?: number | null;
  max: number | null;
  buckets?: Array<{
    label: string;
    min: number;
    max: number | null;
    count: number;
  }>;
}

export interface DataSummaryMediaScopeCoverage {
  total: number;
  local: number;
  ocr_completed_images: number;
  ocr_covered_posts: number;
  vision_analyzed_images: number;
  vision_covered_posts: number;
}

export interface DataSummaryTopPost {
  id: number;
  title: string;
  author_id?: number | null;
  author_name: string;
  note_type: string;
  publish_date: string;
  likes_count: number | null;
  favorites_count: number | null;
  comments_count: number | null;
  total_interactions?: number | null;
  popularity_percentile?: number | null;
  popularity_level?: string;
  has_detail: boolean;
  has_ocr_result: boolean;
  has_vision_result: boolean;
}

export interface DataSummaryAuthorRow {
  id: number;
  name: string;
  followers_count: number | null;
  following_count?: number | null;
  likes_collections_count?: number | null;
  published_posts?: number | null;
  location?: string;
  post_count: number;
  detailed_post_count: number;
  ocr_post_count: number;
  vision_post_count: number;
  profile_updated: boolean;
  complete_interaction_post_count?: number;
  total_interactions: number | null;
  average_interactions: number | null;
}

export interface DataSummaryNoteworthyPost extends DataSummaryTopPost {
  author: {
    id: number;
    name: string;
    followers_count: number | null;
    project_post_count?: number | null;
    published_posts?: number | null;
    likes_collections_count?: number | null;
  };
  smoothed_interactions_per_1000_followers: number;
  interaction_confidence: number;
  attention_metric: number;
  attention_score: number;
}

export interface DataSummaryPayload extends JsonObject {
  schema_version: number;
  scope: 'project' | 'author';
  captured_at: string;
  subject: { id: number; name: string };
  core: Record<string, number | null>;
  post_completeness: {
    total: number;
    detailed: number;
    ocr: number;
    vision: number;
    missing_publish_date: number;
    missing_interactions: number;
    missing_title: number;
    missing_content: number;
  };
  content: {
    image_posts: number;
    video_posts: number;
    other_posts: number;
    posts_with_media: number;
    posts_with_local_media: number;
    media_count: number;
    local_media_count: number;
    average_media_per_post: number;
    publish_months: Array<{ month: string; count: number }>;
    publish_start: string | null;
    publish_end: string | null;
    publish_daily?: Array<{
      date: string;
      count: number;
      change: number;
      change_rate: number | null;
    }>;
    publish_trend?: {
      granularity: 'day' | 'week' | 'month';
      points: Array<{
        period: string;
        count?: number;
        post_count?: number;
        author_count?: number;
        likes?: number | null;
        likes_valid_post_count?: number;
        favorites?: number | null;
        favorites_valid_post_count?: number;
        comments?: number | null;
        comments_valid_post_count?: number;
      }>;
    };
  };
  interactions: {
    complete_post_count: number;
    total_interactions: number;
    top_10_share: number | null;
    likes: DataSummaryDistribution;
    favorites: DataSummaryDistribution;
    comments: DataSummaryDistribution;
  };
  title_features: {
    with_title: number;
    missing: number;
    numeric: number;
    question: number;
    actionable: number;
    length_average: number | null;
    length_median: number | null;
    length_max: number | null;
  };
  top_posts: DataSummaryTopPost[];
  top_posts_by_metric?: Record<string, DataSummaryTopPost[]>;
  top_posts_ranking: string;
  noteworthy_posts?: {
    criteria: {
      follower_smoothing: number;
      interaction_smoothing: number;
      eligible_post_count: number;
      eligible_author_count: number;
      candidate_count: number;
    };
    items: DataSummaryNoteworthyPost[];
  };
  field_coverage?: {
    posts: {
      total: number;
      title: number;
      content: number;
      publish_date: number;
      note_type: number;
      likes: number;
      favorites: number;
      comments: number;
    };
    media: {
      total: number;
      local: number;
      ocr_completed_images: number;
      ocr_covered_posts: number;
      vision_analyzed_images: number;
      vision_covered_posts: number;
      cover?: DataSummaryMediaScopeCoverage;
      detail?: DataSummaryMediaScopeCoverage;
    };
  };
  author_field_coverage?: {
    total: number;
    profile_updated: number;
    display_name?: number;
    xhs_id?: number;
    followers: number;
    following?: number;
    likes_collections?: number;
    published_posts: number;
    bio: number;
    location: number;
    avatar: number;
  };
  author_completeness?: {
    total: number;
    profile_updated: number;
    with_posts: number;
    with_detailed_posts: number;
    with_ocr_posts: number;
    with_vision_posts: number;
  };
  top_authors?: DataSummaryAuthorRow[];
  author_statistics?: {
    post_count: DataSummaryDistribution;
    followers: DataSummaryDistribution;
    following?: DataSummaryDistribution;
    likes_collections?: DataSummaryDistribution;
    published_posts?: DataSummaryDistribution;
    total_interactions: DataSummaryDistribution;
    average_interactions?: DataSummaryDistribution;
    locations?: Array<{ label: string; count: number }>;
    top_10_post_share: number | null;
    top_10_interaction_share: number | null;
    top_authors_by_metric: Record<string, DataSummaryAuthorRow[]>;
  };
  keywords?: { total: number; manual: number; ai_generated: number };
  tasks?: {
    total: number;
    by_status: Record<string, number>;
    by_type: Record<string, number>;
  };
  author_profile?: {
    profile_updated: boolean;
    last_profile_at: string | null;
    display_name?: string;
    xhs_id?: string;
    bio?: string;
    location?: string;
    followers_count?: number | null;
    following_count?: number | null;
    likes_collections_count?: number | null;
    published_posts?: number | null;
    has_avatar: boolean;
    has_bio: boolean;
    has_xhs_id: boolean;
    has_location: boolean;
    has_followers: boolean;
  };
  freshness: {
    last_task_at?: string | null;
    last_detail_at: string | null;
    last_profile_at: string | null;
    last_ocr_at: string | null;
    last_vision_at: string | null;
  };
}

export interface VisionStatus {
  provider_available: boolean;
  available_posts: number;
  analyzed_posts: number;
  pending_posts: number;
  ocr_provider_available?: boolean;
  ocr_available_posts?: number;
  ocr_processed_posts?: number;
  ocr_pending_posts?: number;
  ocr_other_posts?: number;
  vision_scopes?: Record<ImageScope, VisionScopeStatus>;
  ocr_scopes?: Record<ImageScope, OcrScopeStatus>;
}

export interface VisionScopeStatus {
  available_posts: number;
  analyzed_posts: number;
  pending_posts: number;
  available_images: number;
  analyzed_images: number;
  pending_images: number;
}

export interface OcrScopeStatus {
  available_posts: number;
  processed_posts: number;
  pending_posts: number;
  other_posts: number;
  available_images: number;
  processed_images: number;
  pending_images: number;
}

export interface ReportStatus {
  provider_available: boolean;
  post_count: number;
  author_count: number;
  ocr_post_count: number;
  vision_post_count: number;
}

export type ReportContextDetail = 'brief' | 'standard' | 'detailed';

export type ReportPostSelectionMode = 'representative' | 'expanded' | 'all';
export type ReportPostSection = 'basic' | 'content' | 'ocr' | 'vision';

export interface ReportContextConfiguration {
  authors: { enabled: boolean };
  posts: {
    enabled: boolean;
    selection_mode: ReportPostSelectionMode;
    sections: ReportPostSection[];
  };
}

export interface ReportGenerationConfiguration {
  title: string;
  instructions: string;
  sources?: Array<'data_summary' | 'current_detail'>;
  data_summary_report_id?: number;
  context_config?: ReportContextConfiguration;
  context_detail?: ReportContextDetail;
}

export type ReportPresentationPageMode = 'concise' | 'standard' | 'complete';

export interface ReportPresentationConfiguration {
  title: string;
  page_mode: ReportPresentationPageMode;
  instructions: string;
}

export interface ReportPresentation {
  id: number;
  project_report_id: number | null;
  author_report_id: number | null;
  task_id: string;
  version: number;
  status: 'generating' | 'completed';
  title: string;
  page_mode: ReportPresentationPageMode;
  slide_count: number;
  model: string;
  prompt_version: string;
  generation_config_json: JsonObject;
  generated_at: string;
}

export interface ProjectAuthorUpdateConfiguration {
  scopes: Array<'basic_info' | 'preview_posts' | 'detailed_posts'>;
  target: 'basic_unupdated' | 'posts_unupdated' | 'all';
  batch_size: number;
  max_authors: number;
  preview_limit: number;
  detail_limit: number;
  author_delay_min_seconds: number;
  author_delay_max_seconds: number;
  batch_delay_min_seconds: number;
  batch_delay_max_seconds: number;
  consecutive_failure_limit: number;
}

export interface PostDetailUpdateConfiguration {
  mode: 'selected' | 'batch';
  scope: 'global' | 'project' | 'author';
  scope_id?: number;
  post_ids?: number[];
  target?: 'needs_update' | 'preview' | 'all';
  max_posts: number;
  batch_size: number;
  post_delay_min_seconds: number;
  post_delay_max_seconds: number;
  batch_delay_min_seconds: number;
  batch_delay_max_seconds: number;
  consecutive_failure_limit: number;
}

export interface PostCommentCollectionConfiguration {
  collection_mode: 'continue' | 'refresh';
  requested_pages: number;
  page_delay_min_seconds: number;
  page_delay_max_seconds: number;
  include_sub_comments: boolean;
  sub_comment_page_limit: number;
}

export interface PostCommentCheckpoint {
  status: 'active' | 'exhausted' | 'invalid';
  completed_pages: number;
  last_task_id: string | null;
  last_error: string;
  captured_at: string | null;
  updated_at: string;
}

export interface PostComment {
  id: number;
  post_id: number;
  comment_id: string;
  parent_comment_id: string;
  root_comment_id: string;
  comment_type: 'root' | 'reply_preview';
  is_reply_preview: number;
  author_user_id: string;
  author_name: string;
  author_avatar_url: string;
  content: string;
  likes_count: number;
  published_at: string;
  ip_location: string;
  platform_reply_count: number;
  is_invalid: number;
  page_number: number;
  page_rank: number;
  reply_previews: PostComment[];
}

export interface PostCommentsPage {
  items: PostComment[];
  page: number;
  page_size: number;
  total: number;
  summary: {
    platform_comment_count: number | null;
    root_comment_count: number;
    reply_preview_count: number;
    reply_count: number;
    last_comments_fetched_at: string | null;
    latest_task: Task | null;
    active_task: Task | null;
    checkpoint: PostCommentCheckpoint | null;
  };
}

export interface AppSettings {
  host: string;
  port: number;
  /** @deprecated 仅兼容旧版设置响应。 */
  collector?: string;
  /** @deprecated 仅兼容旧版设置响应。 */
  collector_bin?: string;
  collectors: CollectorOption[];
  collector_commands?: CollectorCommand[];
  routing_mode?: 'capability';
  capability_routes?: CapabilityRoute[];
  socai_bin: string;
  xiaohongshu_cli_bin: string;
  xiaohongshu_cookie_source: 'auto' | 'chrome' | 'edge' | 'brave' | 'firefox' | 'safari';
  opencli_bin?: string;
  codex_bin: string;
  data_dir: string;
  detail_ttl_days: number;
  author_ttl_days: number;
  max_author_notes: number;
  max_keywords_per_task: number;
  max_authors_per_task: number;
  default_keyword_author_limit: number;
  research_workers: number;
  vision_workers: number;
  report_workers: number;
  my_author_id?: number | null;
  default_discovery: number;
  default_deep: number;
  vision_analysis_mode: VisionConfiguration['mode'];
  vision_analysis_ratio: number;
  vision_analysis_count: number;
  vision_analysis_max_count: number;
  vision_analysis_batch_size: number;
  vision_model: string;
  vision_reasoning_effort: VisionReasoningEffort;
  vision_timeout_seconds: number;
  post_delay_min_seconds: number;
  post_delay_max_seconds: number;
  batch_delay_min_seconds: number;
  batch_delay_max_seconds: number;
  report_prompt_templates: ReportPromptTemplates;
  report_prompt_defaults: ReportPromptTemplates;
  report_prompt_template_hash: string;
}

export type VisionReasoningEffort =
  | 'default'
  | 'low'
  | 'medium'
  | 'high'
  | 'xhigh'
  | 'max'
  | 'ultra';

export interface VisionModelOption {
  id: string;
  label: string;
  default_reasoning_effort: string;
  reasoning_efforts: VisionReasoningEffort[];
}

export interface VisionModelCatalog {
  available: boolean;
  models: VisionModelOption[];
  error: string;
}

export interface ReportPromptTemplates {
  chunk: string;
  final: string;
}

export interface CollectorOption {
  id: string;
  label: string;
  binary: string;
  available: boolean;
  /** @deprecated 旧版任务级默认提供方标记。 */
  default?: boolean;
  capabilities: string[];
}

export interface CapabilityRoute {
  capability: string;
  label: string;
  description: string;
  commands: string[];
  default_commands: string[];
  /** @deprecated 兼容旧版按提供方展示。 */
  providers: string[];
}

export interface CollectorCommand {
  id: string;
  capability: string;
  provider_id: string;
  label: string;
  instruction: string;
  available: boolean;
}

export interface KeywordCandidate {
  keyword: string;
  reason?: string;
}
