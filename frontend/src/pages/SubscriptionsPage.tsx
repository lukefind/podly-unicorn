import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { feedsApi } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { Navigate } from 'react-router-dom';
import { useState } from 'react';
import toast from 'react-hot-toast';

export default function SubscriptionsPage() {
  const { user, requireAuth } = useAuth();
  const [expandedSubscribers, setExpandedSubscribers] = useState<Record<number, boolean>>({});
  const [settingsModalFeedId, setSettingsModalFeedId] = useState<number | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin-feed-subscriptions'],
    queryFn: feedsApi.getAdminFeedSubscriptions,
    enabled: user?.role === 'admin',
  });

  // useMemo must be called before any early returns (React rules of hooks)
  const feeds = data?.feeds ?? [];
  const selectedFeed = feeds.find(f => f.id === settingsModalFeedId);

  const visibilityMutation = useMutation({
    mutationFn: ({ feedId, isHidden }: { feedId: number; isHidden: boolean }) =>
      feedsApi.setFeedVisibility(feedId, isHidden),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['admin-feed-subscriptions'] });
      toast.success(data.is_hidden ? 'Feed hidden from browse' : 'Feed visible in browse');
    },
    onError: () => {
      toast.error('Failed to update feed visibility');
    },
  });

  const disableAutoProcessMutation = useMutation({
    mutationFn: (feedId: number) => feedsApi.disableAutoProcessAll(feedId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['admin-feed-subscriptions'] });
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      toast.success(`Auto-process disabled for ${data.subscriptions_updated} subscription(s)`);
      setSettingsModalFeedId(null);
    },
    onError: () => {
      toast.error('Failed to disable auto-process');
    },
  });

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    const remainingMins = minutes % 60;
    return `${hours}h ${remainingMins}m`;
  };

  // Redirect non-admins
  if (requireAuth && user && user.role !== 'admin') {
    return <Navigate to="/podcasts" replace />;
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-600" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
          Failed to load subscription data
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-purple-100">Feed Subscriptions</h1>
          <p className="text-sm text-gray-500 mt-1">
            Overview of all podcast feeds and their subscribers
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:gap-4 text-sm">
          <div className="bg-purple-100 text-purple-700 px-2.5 py-1 rounded-lg font-medium">
            {data?.total_feeds || 0} feeds
          </div>
          <div className="bg-cyan-100 text-cyan-700 px-2.5 py-1 rounded-lg font-medium">
            {data?.total_subscriptions || 0} subscriptions
          </div>
        </div>
      </div>

      {/* Feeds Grid */}
      <div className="space-y-4">
        {feeds.map((feed) => (
          <div
            key={feed.id}
            className="bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 shadow-sm overflow-hidden"
          >
            <div className="p-4 sm:p-5">
              <div className="flex items-start gap-3 sm:gap-4">
                {/* Feed Image */}
                {feed.image_url ? (
                  <img
                    src={feed.image_url}
                    alt={feed.title}
                    className="w-14 h-14 sm:w-16 sm:h-16 rounded-lg object-cover flex-shrink-0"
                  />
                ) : (
                  <div className="w-14 h-14 sm:w-16 sm:h-16 rounded-lg bg-purple-100 flex items-center justify-center flex-shrink-0">
                    <svg className="w-8 h-8 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                    </svg>
                  </div>
                )}

                {/* Feed Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-semibold text-gray-900 dark:text-purple-100 text-base sm:text-lg leading-snug">{feed.title}</h3>
                    {feed.auto_process_enabled && (
                      <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400" title="Auto-process enabled">
                        Auto
                      </span>
                    )}
                    {feed.is_hidden ? (
                      <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300" title="Admin hidden from browse page">
                        Hidden
                      </span>
                    ) : !feed.has_public_subscriber ? (
                      <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400" title="All subscribers are private - not visible in Browse Podcasts">
                        Private Only
                      </span>
                    ) : (
                      <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400" title="Visible in Browse Podcasts">
                        Public
                      </span>
                    )}
                  </div>
                  {feed.author && (
                    <p className="text-sm text-gray-500">{feed.author}</p>
                  )}
                  
                  {/* Stats Row */}
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-sm">
                    <span className="text-gray-600 dark:text-purple-300">
                      <span className="font-medium">{feed.posts_count}</span> episodes
                    </span>
                    <span className="text-green-600 dark:text-green-400">
                      <span className="font-medium">{feed.stats.processed_count}</span> processed
                    </span>
                    {feed.stats.total_ad_time_removed > 0 && (
                      <span className="text-pink-600 dark:text-pink-400">
                        <span className="font-medium">{formatDuration(feed.stats.total_ad_time_removed)}</span> ads removed
                      </span>
                    )}
                  </div>
                </div>

                {/* Settings Button + Subscriber Count */}
                <div className="flex-shrink-0 flex items-start gap-2">
                  <button
                    onClick={() => setSettingsModalFeedId(feed.id)}
                    className="p-2 text-gray-400 hover:text-purple-600 hover:bg-purple-50 rounded-lg transition-colors"
                    title="Feed settings"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                  </button>
                  <div className={`px-3 py-1.5 sm:px-4 sm:py-2 rounded-lg text-center ${
                    feed.subscriber_count > 0 
                      ? 'bg-purple-100 text-purple-700' 
                      : 'bg-gray-100 text-gray-500'
                  }`}>
                    <div className="text-xl sm:text-2xl font-bold">{feed.subscriber_count}</div>
                    <div className="text-xs">subscriber{feed.subscriber_count !== 1 ? 's' : ''}</div>
                  </div>
                </div>
              </div>

              {/* Subscribers List */}
              {feed.subscribers.length > 0 && (
                <div className="mt-4 pt-4 border-t border-purple-100">
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <div className="text-xs font-medium text-gray-500">Subscribers</div>
                    {feed.subscribers.length > 4 && (
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedSubscribers((prev) => ({
                            ...prev,
                            [feed.id]: !prev[feed.id],
                          }))
                        }
                        className="text-xs font-medium text-purple-700 hover:text-purple-800"
                      >
                        {expandedSubscribers[feed.id] ? 'Show less' : `+${feed.subscribers.length - 4} more`}
                      </button>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {(expandedSubscribers[feed.id] ? feed.subscribers : feed.subscribers.slice(0, 4)).map((sub) => (
                      <div
                        key={sub.user_id}
                        className={`inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-sm ${
                          (sub as any).is_private 
                            ? 'bg-gray-100 text-gray-500' 
                            : 'bg-purple-50 text-purple-700'
                        }`}
                        title={(sub as any).is_private ? 'Private subscription' : ''}
                      >
                        <div className={`w-5 h-5 rounded-full flex items-center justify-center text-white text-xs font-bold ${
                          (sub as any).is_private 
                            ? 'bg-gray-400' 
                            : 'bg-gradient-to-br from-pink-400 via-purple-400 to-cyan-400'
                        }`}>
                          {sub.username.charAt(0).toUpperCase()}
                        </div>
                        <span className="font-medium max-w-[8rem] truncate">{sub.username}</span>
                        {(sub as any).is_private && (
                          <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                          </svg>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {feed.subscribers.length === 0 && (
                <div className="mt-4 pt-4 border-t border-purple-100">
                  <p className="text-sm text-gray-400 italic">No subscribers yet</p>
                </div>
              )}
            </div>
          </div>
        ))}

        {feeds.length === 0 && (
          <div className="text-center py-12 bg-white/80 rounded-xl border border-purple-200/50">
            <p className="text-gray-500">No feeds have been added yet</p>
          </div>
        )}
      </div>

      {/* Settings Modal */}
      {settingsModalFeedId && selectedFeed && (
        <div 
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={() => setSettingsModalFeedId(null)}
        >
          <div 
            className="bg-white rounded-xl shadow-xl max-w-md w-full overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-4 border-b border-gray-100 bg-gradient-to-r from-pink-50 via-purple-50 to-cyan-50">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-gray-900">Feed Settings</h3>
                <button
                  onClick={() => setSettingsModalFeedId(null)}
                  className="p-1 text-gray-400 hover:text-gray-600 rounded"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <p className="text-sm text-gray-500 mt-1 truncate">{selectedFeed.title}</p>
            </div>

            <div className="p-4 space-y-4">
              {/* Visibility Toggle */}
              <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                <div>
                  <div className="font-medium text-gray-900 text-sm">Hide from Browse</div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    Hidden feeds won't appear in "Browse Podcasts on Server"
                  </div>
                </div>
                <button
                  onClick={() => visibilityMutation.mutate({ 
                    feedId: selectedFeed.id, 
                    isHidden: !selectedFeed.is_hidden 
                  })}
                  disabled={visibilityMutation.isPending}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                    selectedFeed.is_hidden ? 'bg-purple-600' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      selectedFeed.is_hidden ? 'translate-x-6' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>

              {/* Auto-Process Toggle */}
              <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                <div>
                  <div className="font-medium text-gray-900 text-sm">Auto-Process</div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    {selectedFeed.auto_process_enabled 
                      ? 'Enabled by a user - new episodes auto-process'
                      : 'Disabled - no auto-processing'}
                  </div>
                </div>
                <button
                  onClick={() => {
                    if (selectedFeed.auto_process_enabled) {
                      disableAutoProcessMutation.mutate(selectedFeed.id);
                    }
                  }}
                  disabled={disableAutoProcessMutation.isPending || !selectedFeed.auto_process_enabled}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                    selectedFeed.auto_process_enabled ? 'bg-emerald-500' : 'bg-gray-300'
                  } ${!selectedFeed.auto_process_enabled ? 'opacity-50 cursor-not-allowed' : ''}`}
                  title={selectedFeed.auto_process_enabled ? 'Click to disable for all users' : 'No users have enabled auto-process'}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      selectedFeed.auto_process_enabled ? 'translate-x-6' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>
            </div>

            <div className="p-4 border-t border-gray-100 bg-gray-50">
              <button
                onClick={() => setSettingsModalFeedId(null)}
                className="w-full px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
