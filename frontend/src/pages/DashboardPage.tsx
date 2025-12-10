import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { feedsApi, presetsApi } from '../services/api';
import { toast } from 'react-hot-toast';
import type { PromptPreset, Feed } from '../types';

export default function DashboardPage() {
  const queryClient = useQueryClient();

  const { data: feeds } = useQuery({
    queryKey: ['feeds'],
    queryFn: feedsApi.getFeeds,
  });

  const { data: presets } = useQuery({
    queryKey: ['presets'],
    queryFn: presetsApi.getPresets,
  });

  const { data: statsSummary } = useQuery({
    queryKey: ['stats-summary'],
    queryFn: presetsApi.getStatsSummary,
  });

  const { data: jobs } = useQuery({
    queryKey: ['jobs'],
    queryFn: feedsApi.getJobs,
    refetchInterval: 5000,
  });

  const activatePresetMutation = useMutation({
    mutationFn: (presetId: number) => presetsApi.activatePreset(presetId),
    onSuccess: (data: { message: string }) => {
      toast.success(data.message);
      queryClient.invalidateQueries({ queryKey: ['presets'] });
    },
    onError: () => {
      toast.error('Failed to activate preset');
    },
  });

  const refreshAllMutation = useMutation({
    mutationFn: () => feedsApi.refreshAllFeeds(),
    onSuccess: (data) => {
      toast.success(`Refreshed ${data.feeds_refreshed} feeds`);
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });

  const activePreset = presets?.find((p: PromptPreset) => p.is_active);
  const activeJobs = jobs?.filter((j: { status: string }) => j.status === 'running' || j.status === 'pending') || [];
  const feedsArray = Array.isArray(feeds) ? feeds : [];

  const getAggressivenessColor = (level: string) => {
    switch (level) {
      case 'conservative': return { bg: 'bg-green-100', text: 'text-green-700', border: 'border-green-200' };
      case 'balanced': return { bg: 'bg-yellow-100', text: 'text-yellow-700', border: 'border-yellow-200' };
      case 'aggressive': return { bg: 'bg-orange-100', text: 'text-orange-700', border: 'border-orange-200' };
      case 'maximum': return { bg: 'bg-red-100', text: 'text-red-700', border: 'border-red-200' };
      default: return { bg: 'bg-gray-100', text: 'text-gray-700', border: 'border-gray-200' };
    }
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold rainbow-text">Dashboard</h1>
          <p className="text-purple-600 mt-1">Overview of your podcast ad removal system ✨</p>
        </div>
        <button
          onClick={() => refreshAllMutation.mutate()}
          disabled={refreshAllMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-pink-500 via-purple-500 to-cyan-500 text-white rounded-xl hover:shadow-lg hover:shadow-purple-500/30 disabled:opacity-50 transition-all"
        >
          <svg className={`w-4 h-4 ${refreshAllMutation.isPending ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refresh All Feeds
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white/80 backdrop-blur-sm rounded-xl border border-pink-200/50 p-6 shadow-sm unicorn-card">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-pink-100 to-pink-200 rounded-xl">
              <svg className="w-6 h-6 text-pink-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            </div>
            <div>
              <p className="text-sm text-purple-500">Podcasts</p>
              <p className="text-2xl font-bold text-purple-900">{feedsArray.length}</p>
            </div>
          </div>
        </div>

        <div className="bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 p-6 shadow-sm unicorn-card">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-purple-100 to-purple-200 rounded-xl">
              <svg className="w-6 h-6 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
              </svg>
            </div>
            <div>
              <p className="text-sm text-purple-500">Episodes Processed</p>
              <p className="text-2xl font-bold text-purple-900">{statsSummary?.total_episodes_processed || 0}</p>
            </div>
          </div>
        </div>

        <div className="bg-white/80 backdrop-blur-sm rounded-xl border border-cyan-200/50 p-6 shadow-sm unicorn-card">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-cyan-100 to-cyan-200 rounded-xl">
              <svg className="w-6 h-6 text-cyan-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
              </svg>
            </div>
            <div>
              <p className="text-sm text-purple-500">Ads Removed</p>
              <p className="text-2xl font-bold text-purple-900">{statsSummary?.total_ad_segments_removed || 0}</p>
            </div>
          </div>
        </div>

        <div className="bg-white/80 backdrop-blur-sm rounded-xl border border-teal-200/50 p-6 shadow-sm unicorn-card">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-gradient-to-br from-teal-100 to-teal-200 rounded-xl">
              <svg className="w-6 h-6 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <p className="text-sm text-purple-500">Time Saved</p>
              <p className="text-2xl font-bold text-purple-900">{statsSummary?.total_time_saved_formatted || '0m'}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Active Preset Card */}
        <div className="lg:col-span-2 bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 shadow-sm overflow-hidden unicorn-card">
          <div className="p-6 border-b border-purple-100/50 bg-gradient-to-r from-pink-50/50 via-purple-50/50 to-cyan-50/50">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-purple-900">Ad Detection Preset ✨</h2>
              <Link to="/presets" className="text-sm text-purple-600 hover:text-purple-700 font-medium">
                Manage Presets →
              </Link>
            </div>
          </div>
          <div className="p-6">
            {activePreset ? (
              <div className="space-y-4">
                <div className="flex items-start gap-4">
                  <div className={`p-3 rounded-lg ${getAggressivenessColor(activePreset.aggressiveness).bg}`}>
                    <svg className={`w-6 h-6 ${getAggressivenessColor(activePreset.aggressiveness).text}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                    </svg>
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-lg font-semibold text-gray-900">{activePreset.name}</h3>
                      <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${getAggressivenessColor(activePreset.aggressiveness).bg} ${getAggressivenessColor(activePreset.aggressiveness).text}`}>
                        {activePreset.aggressiveness}
                      </span>
                    </div>
                    <p className="text-gray-600 mt-1">{activePreset.description}</p>
                    <div className="flex items-center gap-4 mt-3 text-sm text-gray-500">
                      <span>Min confidence: <strong>{(activePreset.min_confidence * 100).toFixed(0)}%</strong></span>
                    </div>
                  </div>
                </div>

                {/* Quick Preset Switcher */}
                <div className="pt-4 border-t border-gray-100">
                  <p className="text-sm text-gray-500 mb-3">Quick switch:</p>
                  <div className="flex flex-wrap gap-2">
                    {presets?.map((preset: PromptPreset) => (
                      <button
                        key={preset.id}
                        onClick={() => !preset.is_active && activatePresetMutation.mutate(preset.id)}
                        disabled={preset.is_active || activatePresetMutation.isPending}
                        className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-all ${
                          preset.is_active
                            ? `${getAggressivenessColor(preset.aggressiveness).bg} ${getAggressivenessColor(preset.aggressiveness).text} border ${getAggressivenessColor(preset.aggressiveness).border}`
                            : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                        }`}
                      >
                        {preset.name}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-center py-8">
                <p className="text-gray-500">No preset active</p>
                <Link to="/presets" className="text-blue-600 hover:text-blue-700 text-sm font-medium mt-2 inline-block">
                  Configure presets →
                </Link>
              </div>
            )}
          </div>
        </div>

        {/* Active Jobs Card */}
        <div className="bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 shadow-sm overflow-hidden unicorn-card">
          <div className="p-6 border-b border-purple-100/50 bg-gradient-to-r from-cyan-50/50 via-purple-50/50 to-pink-50/50">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-purple-900">Active Jobs 💫</h2>
              <Link to="/jobs" className="text-sm text-purple-600 hover:text-purple-700 font-medium">
                View All →
              </Link>
            </div>
          </div>
          <div className="p-4">
            {activeJobs.length > 0 ? (
              <div className="space-y-3">
                {activeJobs.slice(0, 5).map((job: { job_id: string; post_title: string | null; status: string; progress_percentage: number; step_name: string | null }) => (
                  <div key={job.job_id} className="p-3 bg-gradient-to-r from-purple-50/50 to-pink-50/50 rounded-lg border border-purple-100/50">
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-sm font-medium text-purple-900 truncate flex-1">{job.post_title || 'Processing...'}</p>
                      <span className={`ml-2 px-2 py-0.5 text-xs font-medium rounded-full ${
                        job.status === 'running' ? 'bg-purple-100 text-purple-700' : 'bg-pink-100 text-pink-700'
                      }`}>
                        {job.status}
                      </span>
                    </div>
                    <div className="w-full bg-purple-100 rounded-full h-1.5">
                      <div 
                        className="bg-gradient-to-r from-pink-500 via-purple-500 to-cyan-500 h-1.5 rounded-full transition-all"
                        style={{ width: `${job.progress_percentage}%` }}
                      />
                    </div>
                    <p className="text-xs text-purple-500 mt-1">{job.step_name || 'Initializing...'}</p>
                  </div>
                ))}
                {activeJobs.length > 5 && (
                  <p className="text-sm text-gray-500 text-center">+{activeJobs.length - 5} more jobs</p>
                )}
              </div>
            ) : (
              <div className="text-center py-8">
                <svg className="w-12 h-12 text-gray-300 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <p className="text-gray-500 text-sm">No active jobs</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Recent Podcasts */}
      <div className="bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 shadow-sm overflow-hidden unicorn-card">
        <div className="p-6 border-b border-purple-100/50 bg-gradient-to-r from-pink-50/50 via-purple-50/50 to-cyan-50/50">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-purple-900">Your Podcasts 🎧</h2>
            <Link to="/podcasts" className="text-sm text-purple-600 hover:text-purple-700 font-medium">
              View All →
            </Link>
          </div>
        </div>
        <div className="p-4">
          {feedsArray.length > 0 ? (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
              {feedsArray.slice(0, 6).map((feed: Feed) => (
                <Link
                  key={feed.id}
                  to={`/podcasts?feed=${feed.id}`}
                  className="group"
                >
                  <div className="aspect-square rounded-lg overflow-hidden bg-gray-100 mb-2">
                    {feed.image_url ? (
                      <img
                        src={feed.image_url}
                        alt={feed.title}
                        className="w-full h-full object-cover group-hover:scale-105 transition-transform"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <svg className="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                        </svg>
                      </div>
                    )}
                  </div>
                  <p className="text-sm font-medium text-gray-900 line-clamp-2 group-hover:text-blue-600 transition-colors">
                    {feed.title}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">{feed.posts_count} episodes</p>
                </Link>
              ))}
            </div>
          ) : (
            <div className="text-center py-8">
              <svg className="w-12 h-12 text-gray-300 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
              <p className="text-gray-500 text-sm">No podcasts added yet</p>
              <Link to="/podcasts" className="text-blue-600 hover:text-blue-700 text-sm font-medium mt-2 inline-block">
                Add your first podcast →
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
