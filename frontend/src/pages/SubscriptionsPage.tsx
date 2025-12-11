import { useQuery } from '@tanstack/react-query';
import { feedsApi } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { Navigate } from 'react-router-dom';

export default function SubscriptionsPage() {
  const { user, requireAuth } = useAuth();

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin-feed-subscriptions'],
    queryFn: feedsApi.getAdminFeedSubscriptions,
    enabled: user?.role === 'admin',
  });

  // Redirect non-admins
  if (requireAuth && user?.role !== 'admin') {
    return <Navigate to="/podcasts" replace />;
  }

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    const remainingMins = minutes % 60;
    return `${hours}h ${remainingMins}m`;
  };

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
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Feed Subscriptions</h1>
          <p className="text-sm text-gray-500 mt-1">
            Overview of all podcast feeds and their subscribers
          </p>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <div className="bg-purple-100 text-purple-700 px-3 py-1.5 rounded-lg font-medium">
            {data?.total_feeds || 0} feeds
          </div>
          <div className="bg-cyan-100 text-cyan-700 px-3 py-1.5 rounded-lg font-medium">
            {data?.total_subscriptions || 0} subscriptions
          </div>
        </div>
      </div>

      {/* Feeds Grid */}
      <div className="space-y-4">
        {data?.feeds.map((feed) => (
          <div
            key={feed.id}
            className="bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 shadow-sm overflow-hidden"
          >
            <div className="p-5">
              <div className="flex items-start gap-4">
                {/* Feed Image */}
                {feed.image_url ? (
                  <img
                    src={feed.image_url}
                    alt={feed.title}
                    className="w-16 h-16 rounded-lg object-cover flex-shrink-0"
                  />
                ) : (
                  <div className="w-16 h-16 rounded-lg bg-purple-100 flex items-center justify-center flex-shrink-0">
                    <svg className="w-8 h-8 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                    </svg>
                  </div>
                )}

                {/* Feed Info */}
                <div className="flex-1 min-w-0">
                  <h3 className="font-semibold text-gray-900 text-lg">{feed.title}</h3>
                  {feed.author && (
                    <p className="text-sm text-gray-500">{feed.author}</p>
                  )}
                  
                  {/* Stats Row */}
                  <div className="flex items-center gap-4 mt-2 text-sm">
                    <span className="text-gray-600">
                      <span className="font-medium">{feed.posts_count}</span> episodes
                    </span>
                    <span className="text-green-600">
                      <span className="font-medium">{feed.stats.processed_count}</span> processed
                    </span>
                    {feed.stats.total_ad_time_removed > 0 && (
                      <span className="text-pink-600">
                        <span className="font-medium">{formatDuration(feed.stats.total_ad_time_removed)}</span> ads removed
                      </span>
                    )}
                  </div>
                </div>

                {/* Subscriber Count Badge */}
                <div className="flex-shrink-0 text-center">
                  <div className={`px-4 py-2 rounded-lg ${
                    feed.subscriber_count > 0 
                      ? 'bg-purple-100 text-purple-700' 
                      : 'bg-gray-100 text-gray-500'
                  }`}>
                    <div className="text-2xl font-bold">{feed.subscriber_count}</div>
                    <div className="text-xs">subscriber{feed.subscriber_count !== 1 ? 's' : ''}</div>
                  </div>
                </div>
              </div>

              {/* Subscribers List */}
              {feed.subscribers.length > 0 && (
                <div className="mt-4 pt-4 border-t border-purple-100">
                  <div className="text-xs font-medium text-gray-500 mb-2">Subscribers</div>
                  <div className="flex flex-wrap gap-2">
                    {feed.subscribers.map((sub) => (
                      <div
                        key={sub.user_id}
                        className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm ${
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
                        <span className="font-medium">{sub.username}</span>
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

        {data?.feeds.length === 0 && (
          <div className="text-center py-12 bg-white/80 rounded-xl border border-purple-200/50">
            <p className="text-gray-500">No feeds have been added yet</p>
          </div>
        )}
      </div>
    </div>
  );
}
