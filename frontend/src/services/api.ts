import axios from 'axios';
import type {
  Feed,
  Episode,
  Job,
  JobManagerStatus,
  CombinedConfig,
  LLMConfig,
  WhisperConfig,
  PodcastSearchResult,
  ConfigResponse,
  PromptPreset,
  ProcessingStatsSummary,
} from '../types';

const API_BASE_URL = '';

const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
});

const buildAbsoluteUrl = (path: string): string => {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }

  const origin = API_BASE_URL || window.location.origin;
  if (path.startsWith('/')) {
    return `${origin}${path}`;
  }
  return `${origin}/${path}`;
};

export const feedsApi = {
  getFeeds: async (): Promise<Feed[]> => {
    const response = await api.get('/feeds');
    return response.data;
  },

  getFeedPosts: async (feedId: number): Promise<Episode[]> => {
    const response = await api.get(`/api/feeds/${feedId}/posts`);
    return response.data;
  },

  addFeed: async (url: string): Promise<{ status: string; feed_id: number; title: string }> => {
    const formData = new FormData();
    formData.append('url', url);
    const response = await api.post('/feed', formData, {
      headers: { 'Accept': 'application/json' },
    });
    return response.data;
  },

  deleteFeed: async (feedId: number): Promise<void> => {
    await api.delete(`/feed/${feedId}`);
  },

  getFeedShareLink: async (feedId: number): Promise<{
    url: string;
    feed_token: string;
    feed_secret: string;
    feed_id: number;
  }> => {
    const response = await api.post(`/api/feeds/${feedId}/share-link`);
    return response.data;
  },

  refreshFeed: async (
    feedId: number
  ): Promise<{ status: string; message?: string }> => {
    const response = await api.post(`/api/feeds/${feedId}/refresh`);
    return response.data;
  },

  refreshAllFeeds: async (): Promise<{
    status: string;
    feeds_refreshed: number;
    jobs_enqueued: number;
  }> => {
    const response = await api.post('/api/feeds/refresh-all');
    return response.data;
  },

  togglePostWhitelist: async (guid: string, whitelisted: boolean): Promise<void> => {
    await api.post(`/api/posts/${guid}/whitelist`, { whitelisted });
  },

  toggleAllPostsWhitelist: async (feedId: number): Promise<{ message: string; whitelisted_count: number; total_count: number; all_whitelisted: boolean }> => {
    const response = await api.post(`/api/feeds/${feedId}/toggle-whitelist-all`);
    return response.data;
  },

  searchFeeds: async (
    term: string
  ): Promise<{
    results: PodcastSearchResult[];
    total: number;
  }> => {
    const response = await api.get('/api/feeds/search', {
      params: { term },
    });
    return response.data;
  },

  // Feed subscription methods
  getAllFeeds: async (): Promise<(Feed & { is_subscribed: boolean })[]> => {
    const response = await api.get('/api/feeds/all');
    return response.data;
  },

  subscribeFeed: async (feedId: number, isPrivate: boolean = false): Promise<{ message: string; subscribed: boolean; is_private: boolean }> => {
    const response = await api.post(`/api/feeds/${feedId}/subscribe`, { private: isPrivate });
    return response.data;
  },

  unsubscribeFeed: async (feedId: number): Promise<{ message: string; subscribed: boolean }> => {
    const response = await api.post(`/api/feeds/${feedId}/unsubscribe`);
    return response.data;
  },

  // Admin feed subscriptions overview
  getAdminFeedSubscriptions: async (): Promise<{
    feeds: Array<{
      id: number;
      title: string;
      rss_url: string;
      description: string | null;
      author: string | null;
      image_url: string | null;
      posts_count: number;
      subscribers: Array<{
        user_id: number;
        username: string;
        subscribed_at: string | null;
      }>;
      subscriber_count: number;
      stats: {
        processed_count: number;
        total_ad_time_removed: number;
      };
    }>;
    total_feeds: number;
    total_subscriptions: number;
  }> => {
    const response = await api.get('/api/admin/feed-subscriptions');
    return response.data;
  },

  // New post processing methods
  processPost: async (guid: string): Promise<{ status: string; job_id?: string; message: string; download_url?: string }> => {
    const response = await api.post(`/api/posts/${guid}/process`);
    return response.data;
  },

  reprocessPost: async (guid: string): Promise<{ status: string; job_id?: string; message: string; download_url?: string }> => {
    const response = await api.post(`/api/posts/${guid}/reprocess`);
    return response.data;
  },

  getPostStatus: async (guid: string): Promise<{
    status: string;
    step: number;
    step_name: string;
    total_steps: number;
    message: string;
    download_url?: string;
    error?: string;
  }> => {
    const response = await api.get(`/api/posts/${guid}/status`);
    return response.data;
  },

  // Get audio URL for post
  getPostAudioUrl: (guid: string): string => {
    return buildAbsoluteUrl(`/api/posts/${guid}/audio`);
  },

  // Get download URL for processed post
  getPostDownloadUrl: (guid: string): string => {
    return buildAbsoluteUrl(`/api/posts/${guid}/download`);
  },

  // Get download URL for original post
  getPostOriginalDownloadUrl: (guid: string): string => {
    return buildAbsoluteUrl(`/api/posts/${guid}/download/original`);
  },

  // Download processed post
  downloadPost: async (guid: string): Promise<void> => {
    const response = await api.get(`/api/posts/${guid}/download`, {
      responseType: 'blob',
    });

    const blob = new Blob([response.data], { type: 'audio/mpeg' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${guid}.mp3`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
  },

  // Download original post
  downloadOriginalPost: async (guid: string): Promise<void> => {
    const response = await api.get(`/api/posts/${guid}/download/original`, {
      responseType: 'blob',
    });

    const blob = new Blob([response.data], { type: 'audio/mpeg' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${guid}_original.mp3`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
  },

  createProtectedFeedShareLink: async (
    feedId: number
  ): Promise<{ url: string; feed_token: string; feed_secret: string; feed_id: number }> => {
    const response = await api.post(`/api/feeds/${feedId}/share-link`);
    return response.data;
  },

  // Get processing stats for post
  getPostStats: async (guid: string): Promise<{
    post: {
      guid: string;
      title: string;
      duration: number | null;
      release_date: string | null;
      whitelisted: boolean;
      has_processed_audio: boolean;
      processed_with_preset: {
        id: number;
        name: string;
        aggressiveness: string;
        min_confidence: number;
      } | null;
    };
    processing_stats: {
      total_segments: number;
      total_model_calls: number;
      total_identifications: number;
      content_segments: number;
      ad_segments_count: number;
      ad_percentage: number;
      estimated_ad_time_seconds: number;
      model_call_statuses: Record<string, number>;
      model_types: Record<string, number>;
    };
    model_calls: Array<{
      id: number;
      model_name: string;
      status: string;
      segment_range: string;
      first_segment_sequence_num: number;
      last_segment_sequence_num: number;
      timestamp: string | null;
      retry_attempts: number;
      error_message: string | null;
      prompt: string | null;
      response: string | null;
    }>;
    transcript_segments: Array<{
      id: number;
      sequence_num: number;
      start_time: number;
      end_time: number;
      text: string;
      primary_label: 'ad' | 'content';
      identifications: Array<{
        id: number;
        label: string;
        confidence: number | null;
        model_call_id: number;
      }>;
    }>;
    identifications: Array<{
      id: number;
      transcript_segment_id: number;
      label: string;
      confidence: number | null;
      model_call_id: number;
      segment_sequence_num: number;
      segment_start_time: number;
      segment_end_time: number;
      segment_text: string;
    }>;
  }> => {
    const response = await api.get(`/api/posts/${guid}/stats`);
    return response.data;
  },

  // Legacy aliases for backward compatibility
  getFeedEpisodes: async (feedId: number): Promise<Episode[]> => {
    return feedsApi.getFeedPosts(feedId);
  },

  toggleEpisodeWhitelist: async (guid: string, whitelisted: boolean): Promise<void> => {
    return feedsApi.togglePostWhitelist(guid, whitelisted);
  },

  toggleAllEpisodesWhitelist: async (feedId: number): Promise<{ message: string; whitelisted_count: number; total_count: number; all_whitelisted: boolean }> => {
    return feedsApi.toggleAllPostsWhitelist(feedId);
  },

  processEpisode: async (guid: string): Promise<{ status: string; job_id?: string; message: string; download_url?: string }> => {
    return feedsApi.processPost(guid);
  },

  getEpisodeStatus: async (guid: string): Promise<{
    status: string;
    step: number;
    step_name: string;
    total_steps: number;
    message: string;
    download_url?: string;
    error?: string;
  }> => {
    return feedsApi.getPostStatus(guid);
  },

  getEpisodeAudioUrl: (guid: string): string => {
    return feedsApi.getPostAudioUrl(guid);
  },

  getEpisodeStats: async (guid: string): Promise<{
    post: {
      guid: string;
      title: string;
      duration: number | null;
      release_date: string | null;
      whitelisted: boolean;
      has_processed_audio: boolean;
    };
    processing_stats: {
      total_segments: number;
      total_model_calls: number;
      total_identifications: number;
      content_segments: number;
      ad_segments_count: number;
      ad_percentage: number;
      estimated_ad_time_seconds: number;
      model_call_statuses: Record<string, number>;
      model_types: Record<string, number>;
    };
    model_calls: Array<{
      id: number;
      model_name: string;
      status: string;
      segment_range: string;
      first_segment_sequence_num: number;
      last_segment_sequence_num: number;
      timestamp: string | null;
      retry_attempts: number;
      error_message: string | null;
      prompt: string | null;
      response: string | null;
    }>;
    transcript_segments: Array<{
      id: number;
      sequence_num: number;
      start_time: number;
      end_time: number;
      text: string;
      primary_label: 'ad' | 'content';
      identifications: Array<{
        id: number;
        label: string;
        confidence: number | null;
        model_call_id: number;
      }>;
    }>;
    identifications: Array<{
      id: number;
      transcript_segment_id: number;
      label: string;
      confidence: number | null;
      model_call_id: number;
      segment_sequence_num: number;
      segment_start_time: number;
      segment_end_time: number;
      segment_text: string;
    }>;
  }> => {
    return feedsApi.getPostStats(guid);
  },

  // Legacy download aliases
  downloadEpisode: async (guid: string): Promise<void> => {
    return feedsApi.downloadPost(guid);
  },

  downloadOriginalEpisode: async (guid: string): Promise<void> => {
    return feedsApi.downloadOriginalPost(guid);
  },

  getEpisodeDownloadUrl: (guid: string): string => {
    return feedsApi.getPostDownloadUrl(guid);
  },

  getEpisodeOriginalDownloadUrl: (guid: string): string => {
    return feedsApi.getPostOriginalDownloadUrl(guid);
  },

  getJobs: async (): Promise<Job[]> => {
    const response = await api.get('/api/jobs');
    return response.data.jobs || [];
  },
};

export const authApi = {
  getStatus: async (): Promise<{ require_auth: boolean }> => {
    const response = await api.get('/api/auth/status');
    return response.data;
  },

  login: async (username: string, password: string): Promise<{ user: { id: number; username: string; role: string } }> => {
    const response = await api.post('/api/auth/login', { username, password });
    return response.data;
  },

  logout: async (): Promise<void> => {
    await api.post('/api/auth/logout');
  },

  getCurrentUser: async (): Promise<{ user: { id: number; username: string; role: string } }> => {
    const response = await api.get('/api/auth/me');
    return response.data;
  },

  changePassword: async (payload: { current_password: string; new_password: string }): Promise<{ status: string }> => {
    const response = await api.post('/api/auth/change-password', payload);
    return response.data;
  },

  listUsers: async (): Promise<{ users: Array<{ id: number; username: string; role: string; created_at: string; updated_at: string }> }> => {
    const response = await api.get('/api/auth/users');
    return response.data;
  },

  createUser: async (payload: { username: string; password: string; role: string }): Promise<{ user: { id: number; username: string; role: string; created_at: string; updated_at: string } }> => {
    const response = await api.post('/api/auth/users', payload);
    return response.data;
  },

  updateUser: async (username: string, payload: { password?: string; role?: string }): Promise<{ status: string }> => {
    const response = await api.patch(`/api/auth/users/${username}`, payload);
    return response.data;
  },

  deleteUser: async (username: string): Promise<{ status: string }> => {
    const response = await api.delete(`/api/auth/users/${username}`);
    return response.data;
  },

  getUserStats: async (): Promise<UserStatsResponse> => {
    const response = await api.get('/api/admin/user-stats');
    return response.data;
  },
};

export interface UserStats {
  id: number;
  username: string;
  role: string;
  created_at: string;
  episodes_processed: number;
  ad_time_removed_seconds: number;
  ad_time_removed_formatted: string;
  total_downloads: number;
  processed_downloads: number;
  subscriptions_count: number;
  last_activity: string | null;
  recent_downloads: Array<{
    post_id: number;
    post_title: string;
    downloaded_at: string;
    is_processed: boolean;
  }>;
}

export interface UserStatsResponse {
  users: UserStats[];
  global_stats: {
    total_feeds: number;
    total_episodes: number;
    total_processed: number;
  };
}

export const configApi = {
  getConfig: async (): Promise<ConfigResponse> => {
    const response = await api.get('/api/config');
    return response.data;
  },
  isConfigured: async (): Promise<{ configured: boolean }> => {
    const response = await api.get('/api/config/api_configured_check');
    return { configured: !!response.data?.configured };
  },
  updateConfig: async (payload: Partial<CombinedConfig>): Promise<CombinedConfig> => {
    const response = await api.put('/api/config', payload);
    return response.data;
  },
  testLLM: async (
    payload: Partial<{ llm: LLMConfig }>
  ): Promise<{ ok: boolean; message?: string; error?: string }> => {
    const response = await api.post('/api/config/test-llm', payload ?? {});
    return response.data;
  },
  testWhisper: async (
    payload: Partial<{ whisper: WhisperConfig }>
  ): Promise<{ ok: boolean; message?: string; error?: string }> => {
    const response = await api.post('/api/config/test-whisper', payload ?? {});
    return response.data;
  },
  getWhisperCapabilities: async (): Promise<{ local_available: boolean }> => {
    const response = await api.get('/api/config/whisper-capabilities');
    const local_available = !!response.data?.local_available;
    return { local_available };
  },
};

export const jobsApi = {
  getActiveJobs: async (limit: number = 100): Promise<Job[]> => {
    const response = await api.get('/api/jobs/active', { params: { limit } });
    return response.data;
  },
  getAllJobs: async (limit: number = 200): Promise<Job[]> => {
    const response = await api.get('/api/jobs/all', { params: { limit } });
    return response.data;
  },
  cancelJob: async (jobId: string): Promise<{ status: string; job_id: string; message: string }> => {
    const response = await api.post(`/api/jobs/${jobId}/cancel`);
    return response.data;
  },
  getJobManagerStatus: async (): Promise<JobManagerStatus> => {
    const response = await api.get('/api/job-manager/status');
    return response.data;
  },
  clearHistory: async (): Promise<{ status: string; deleted_count: number; message: string }> => {
    const response = await api.post('/api/jobs/clear-history');
    return response.data;
  }
};

export const presetsApi = {
  getPresets: async (): Promise<PromptPreset[]> => {
    const response = await api.get('/api/presets');
    return response.data.presets;
  },

  getPreset: async (id: number): Promise<PromptPreset> => {
    const response = await api.get(`/api/presets/${id}`);
    return response.data.preset;
  },

  activatePreset: async (id: number): Promise<{ message: string; preset: PromptPreset }> => {
    const response = await api.post(`/api/presets/${id}/activate`);
    return response.data;
  },

  createPreset: async (data: Partial<PromptPreset>): Promise<{ message: string; preset: PromptPreset }> => {
    const response = await api.post('/api/presets', data);
    return response.data;
  },

  updatePreset: async (id: number, data: Partial<PromptPreset>): Promise<{ message: string; preset: PromptPreset }> => {
    const response = await api.put(`/api/presets/${id}`, data);
    return response.data;
  },

  deletePreset: async (id: number): Promise<{ message: string }> => {
    const response = await api.delete(`/api/presets/${id}`);
    return response.data;
  },

  getStatsSummary: async (): Promise<ProcessingStatsSummary> => {
    const response = await api.get('/api/statistics/summary');
    return response.data;
  },
};
