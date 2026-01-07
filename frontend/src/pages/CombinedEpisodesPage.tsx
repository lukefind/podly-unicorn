import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { feedsApi } from '../services/api';
import { toast } from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { copyTextToClipboard } from '../services/clipboard';

export default function CombinedEpisodesPage() {
  const queryClient = useQueryClient();
  const { requireAuth } = useAuth();
  const [showUnprocessedOnly, setShowUnprocessedOnly] = useState(false);
  const [showQueuedOnly, setShowQueuedOnly] = useState(false);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['combined-episodes', showUnprocessedOnly, showQueuedOnly],
    queryFn: () => feedsApi.getCombinedEpisodes({
      limit: 100,
      unprocessed_only: showUnprocessedOnly,
      queued_only: showQueuedOnly,
    }),
    refetchInterval: showQueuedOnly ? 5000 : false,
  });

  const processMutation = useMutation({
    mutationFn: (guid: string) => feedsApi.processPost(guid),
    onSuccess: () => {
      toast.success('Processing started');
      queryClient.invalidateQueries({ queryKey: ['combined-episodes'] });
    },
    onError: () => {
      toast.error('Failed to start processing');
    },
  });

  const formatDate = (dateString: string | null) => {
    if (!dateString) return 'Unknown date';
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
  };

  const copyUrl = async (url: string, label: string) => {
    try {
      await copyTextToClipboard(window.location.origin + url);
      toast.success(`${label} copied!`);
    } catch {
      toast.error('Failed to copy');
    }
  };

  if (!requireAuth) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-gray-500 dark:text-gray-400">Combined episodes requires authentication to be enabled.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-600" />
      </div>
    );
  }

  const episodes = data?.episodes || [];
  const subscribedFeeds = data?.subscribed_feeds || 0;

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <img src="/images/logos/unicorn-logo.png" alt="" className="w-10 h-10" />
          <div>
            <h1 className="text-xl font-bold text-purple-900 dark:text-purple-100">Combined Episodes</h1>
            <p className="text-sm text-purple-600 dark:text-purple-400">
              {subscribedFeeds} subscribed shows • {data?.total || 0} episodes
            </p>
          </div>
        </div>
        <button
          onClick={() => refetch()}
          className="px-3 py-2 text-sm font-medium rounded-lg bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 hover:bg-purple-200 dark:hover:bg-purple-900/60 transition-colors"
        >
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6">
        <label className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white dark:bg-gray-800 border border-purple-200 dark:border-purple-700 cursor-pointer">
          <input
            type="checkbox"
            checked={showUnprocessedOnly}
            onChange={(e) => {
              setShowUnprocessedOnly(e.target.checked);
              if (e.target.checked) setShowQueuedOnly(false);
            }}
            className="rounded border-purple-300 text-purple-600 focus:ring-purple-500"
          />
          <span className="text-sm text-purple-700 dark:text-purple-300">Unprocessed only</span>
        </label>
        <label className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white dark:bg-gray-800 border border-purple-200 dark:border-purple-700 cursor-pointer">
          <input
            type="checkbox"
            checked={showQueuedOnly}
            onChange={(e) => {
              setShowQueuedOnly(e.target.checked);
              if (e.target.checked) setShowUnprocessedOnly(false);
            }}
            className="rounded border-purple-300 text-purple-600 focus:ring-purple-500"
          />
          <span className="text-sm text-purple-700 dark:text-purple-300">Queued only</span>
        </label>
      </div>

      {/* Episodes List */}
      {episodes.length === 0 ? (
        <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-xl border border-purple-200 dark:border-purple-700">
          <p className="text-purple-600 dark:text-purple-400">
            {showUnprocessedOnly ? 'No unprocessed episodes' : showQueuedOnly ? 'No queued episodes' : 'No episodes found'}
          </p>
          <p className="text-sm text-purple-400 dark:text-purple-500 mt-1">
            Subscribe to podcasts to see episodes here
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {episodes.map((episode) => (
            <div
              key={episode.guid}
              className="p-4 rounded-xl bg-white dark:bg-gray-800 border border-purple-200 dark:border-purple-700 shadow-sm"
            >
              {/* Top row: Title + Status */}
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="flex-1 min-w-0">
                  <h3 className="font-medium text-purple-900 dark:text-purple-100 line-clamp-2">
                    {episode.title}
                  </h3>
                  <p className="text-sm text-purple-600 dark:text-purple-400 mt-0.5">
                    {episode.feed_title}
                  </p>
                </div>
                <StatusBadge status={episode.status} job={episode.job} />
              </div>

              {/* Metadata */}
              <div className="flex items-center gap-2 text-sm text-purple-400 dark:text-purple-500 mb-3">
                <span>{formatDate(episode.release_date)}</span>
                {episode.duration && (
                  <>
                    <span>•</span>
                    <span>{formatDuration(episode.duration)}</span>
                  </>
                )}
              </div>

              {/* Actions */}
              <div className="flex flex-wrap items-center gap-2">
                {/* Process button */}
                {episode.status === 'not_processed' && episode.whitelisted && (
                  <button
                    onClick={() => processMutation.mutate(episode.guid)}
                    disabled={processMutation.isPending}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg bg-purple-600 text-white hover:bg-purple-700 transition-colors disabled:opacity-50"
                  >
                    Process now
                  </button>
                )}

                {/* Copy trigger link */}
                {episode.trigger_url && (
                  <button
                    onClick={() => copyUrl(episode.trigger_url!, 'Trigger link')}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 hover:bg-purple-200 dark:hover:bg-purple-900/60 transition-colors"
                  >
                    Copy trigger link
                  </button>
                )}

                {/* Copy enclosure URL */}
                {episode.enclosure_url && (
                  <button
                    onClick={() => copyUrl(episode.enclosure_url!, 'Enclosure URL')}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
                  >
                    Copy enclosure URL
                  </button>
                )}

                {/* View in feed */}
                <a
                  href={`/podcasts?feed=${episode.feed_id}`}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg text-purple-600 dark:text-purple-400 hover:underline"
                >
                  View in feed →
                </a>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status, job }: { status: string; job: { progress_percentage: number; step_name: string } | null }) {
  switch (status) {
    case 'ready':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400 rounded-lg">
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
          </svg>
          Ready
        </span>
      );
    case 'processing':
    case 'queued':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400 rounded-lg">
          <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          {job ? `${Math.round(job.progress_percentage)}%` : status === 'queued' ? 'Queued' : 'Processing'}
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 rounded-lg">
          Not processed
        </span>
      );
  }
}
