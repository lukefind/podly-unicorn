export interface Feed {
  id: number;
  rss_url: string;
  title: string;
  description?: string;
  author?: string;
  image_url?: string;
  posts_count: number;
  is_private?: boolean;
  default_prompt_preset?: { id: number; name: string } | null;
  effective_prompt_preset?: { id: number; name: string } | null;
  auto_download_enabled?: boolean;
  auto_download_enabled_by_user?: boolean;
  auto_download_enabled_by_other?: boolean;
}

export interface Episode {
  id: number;
  guid: string;
  title: string;
  description: string;
  release_date: string | null;
  duration: number | null;
  whitelisted: boolean;
  has_processed_audio: boolean;
  has_unprocessed_audio: boolean;
  download_url: string;
  image_url: string | null;
  download_count: number;
} 

export interface Job {
  job_id: string;
  post_guid: string;
  post_title: string | null;
  feed_id: number | null;
  feed_title: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'skipped' | string;
  priority: number;
  step: number;
  step_name: string | null;
  total_steps: number;
  progress_percentage: number;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  trigger_source: 'manual_ui' | 'manual_reprocess' | 'auto_feed_refresh' | 'on_demand_rss' | string | null;
  triggered_by_user_id: number | null;
  triggered_by_username: string | null;
}

export interface JobManagerRun {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  trigger: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string | null;
  total_jobs: number;
  queued_jobs: number;
  running_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  skipped_jobs: number;
  context?: Record<string, unknown> | null;
  counters_reset_at: string | null;
  progress_percentage: number;
}

export interface JobManagerStatus {
  run: JobManagerRun | null;
}

// ----- Configuration Types -----

export interface LLMConfig {
  llm_api_key?: string | null;
  llm_api_key_ref?: string | null;
  llm_api_key_preview?: string | null;
  llm_model: string;
  openai_base_url?: string | null;
  openai_timeout: number;
  openai_max_tokens: number;
  llm_max_concurrent_calls: number;
  llm_max_retry_attempts: number;
  llm_max_input_tokens_per_call?: number | null;
  llm_enable_token_rate_limiting: boolean;
  llm_max_input_tokens_per_minute?: number | null;
  enable_boundary_refinement: boolean;
  enable_word_level_boundary_refiner: boolean;
}

export type WhisperConfig =
  | { whisper_type: 'local'; model: string }
  | {
      whisper_type: 'remote';
      model: string;
      api_key?: string | null;
      api_key_preview?: string | null;
      base_url?: string;
      language: string;
      timeout_sec: number;
      chunksize_mb: number;
    }
  | {
      whisper_type: 'groq';
      api_key?: string | null;
      api_key_preview?: string | null;
      model: string;
      language: string;
      max_retries: number;
    }
  | { whisper_type: 'test' };

export interface ProcessingConfigUI {
  num_segments_to_input_to_prompt: number;
}

export interface OutputConfigUI {
  fade_ms: number;
  // Note the intentional spelling to match backend
  min_ad_segement_separation_seconds: number;
  min_ad_segment_length_seconds: number;
  min_confidence: number;
}

export interface AppConfigUI {
  background_update_interval_minute: number | null;
  automatically_whitelist_new_episodes: boolean;
  post_cleanup_retention_days: number | null;
  number_of_episodes_to_whitelist_from_archive_of_new_feed: number;
  allow_signup: boolean;
}

export interface EmailConfigUI {
  smtp_host?: string | null;
  smtp_port?: number | null;
  smtp_username?: string | null;
  smtp_password?: string | null;
  smtp_password_preview?: string | null;
  smtp_use_tls?: boolean;
  smtp_use_ssl?: boolean;
  from_email?: string | null;
  admin_notify_email?: string | null;
  app_base_url?: string | null;
}

export interface CombinedConfig {
  llm: LLMConfig;
  whisper: WhisperConfig;
  processing: ProcessingConfigUI;
  output: OutputConfigUI;
  app: AppConfigUI;
  email?: EmailConfigUI;
}

export interface EnvOverrideEntry {
  env_var: string;
  value?: string;
  value_preview?: string | null;
  is_secret?: boolean;
}

export type EnvOverrideMap = Record<string, EnvOverrideEntry>;

export interface ConfigResponse {
  config: CombinedConfig;
  env_overrides?: EnvOverrideMap;
}

export interface LLMProviderOption {
  id: string;
  label: string;
  default_model?: string | null;
  default_openai_base_url?: string | null;
}

export interface LLMModelOption {
  provider: string;
  value: string;
}

export interface LLMEnvKeyOption {
  ref: string;
  env_var: string;
  provider: string;
  provider_label: string;
  api_key_preview?: string | null;
  default_model?: string | null;
  default_openai_base_url?: string | null;
}

export interface LLMSavedKeyOption {
  id: number;
  ref: string;
  name: string;
  provider: string;
  provider_label: string;
  api_key_preview: string;
  default_model?: string | null;
  default_openai_base_url?: string | null;
  created_at?: string | null;
  last_used_at?: string | null;
}

export interface LLMOptionsResponse {
  providers: LLMProviderOption[];
  models: LLMModelOption[];
  env_keys: LLMEnvKeyOption[];
  saved_keys: LLMSavedKeyOption[];
  current?: {
    key_ref?: string | null;
    provider?: string | null;
    model?: string | null;
    openai_base_url?: string | null;
  };
}

export interface PodcastSearchResult {
  title: string;
  author: string;
  feedUrl: string;
  artworkUrl: string;
  description: string;
  genres: string[];
}

export interface AuthUser {
  id: number;
  username: string;
  email?: string | null;
  role: 'admin' | 'user' | string;
}

export interface ManagedUser extends AuthUser {
  created_at: string;
  updated_at: string;
  account_status?: string;
}

// ----- Preset Types -----

export interface PromptPreset {
  id: number;
  name: string;
  description: string | null;
  aggressiveness: 'conservative' | 'balanced' | 'aggressive' | 'maximum';
  min_confidence: number;
  is_active: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
  system_prompt?: string;
  user_prompt_template?: string;
}

// ----- Jobs Dashboard Types -----

export interface JobsDashboardOverview {
  total_all_time: number;
  total_period: number;
  by_status: Record<string, number>;
  by_trigger_source: Record<string, number>;
}

export interface JobsDashboardDaily {
  date: string;
  total: number;
  completed?: number;
  failed?: number;
  skipped?: number;
  pending?: number;
  running?: number;
  cancelled?: number;
}

export interface JobsDashboardUserRow {
  user_id: number;
  username: string;
  total: number;
  completed: number;
  failed: number;
}

export interface JobsDashboardFeedRow {
  feed_id: number | null;
  title: string;
  image_url: string | null;
  total: number;
  completed: number;
}

export interface JobsDashboardPerformance {
  completed_count: number;
  avg_duration_seconds: number;
  min_duration_seconds: number;
  max_duration_seconds: number;
  total_ads_removed: number;
  total_time_removed_seconds: number;
  avg_percentage_removed: number;
}

export interface JobsDashboardRecentJob {
  job_id: string;
  post_guid: string;
  post_title: string | null;
  feed_title: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  triggered_by: string | null;
  trigger_source: string | null;
  ads_removed: number | null;
  time_removed_seconds: number | null;
  percentage_removed: number | null;
}

export interface JobsDashboard {
  period_days: number;
  overview: JobsDashboardOverview;
  daily: JobsDashboardDaily[];
  by_user: JobsDashboardUserRow[];
  by_feed: JobsDashboardFeedRow[];
  performance: JobsDashboardPerformance;
  recent_completed: JobsDashboardRecentJob[];
}

export interface ProcessingStatsSummary {
  total_episodes_processed: number;
  total_ad_segments_removed: number;
  total_time_saved_seconds: number;
  total_time_saved_formatted: string;
  average_percentage_removed: number;
}
