import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { feedsApi } from '../services/api';
import { toast } from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { copyTextToClipboard } from '../services/clipboard';
import PlayButton from '../components/PlayButton';
import DownloadButton from '../components/DownloadButton';

export default function CombinedEpisodesPage() {
  const queryClient = useQueryClient();
  const { requireAuth } = useAuth();
  const [showUnprocessedOnly, setShowUnprocessedOnly] = useState(false);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['combined-episodes', showUnprocessedOnly],
    queryFn: () => feedsApi.getCombinedEpisodes({
      limit: 100,
      unprocessed_only: showUnprocessedOnly,
    }),
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
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
  };

  const handleCopyRss = async () => {
    try {
      const shareData = await feedsApi.getCombinedFeedShareLink();
      await copyTextToClipboard(shareData.url);
      toast.success('Combined RSS URL copied!');
    } catch {
      toast.error('Failed to copy RSS URL');
    }
  };

  if (!requireAuth) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-gray-500 dark:text-gray-400">Combined episodes requires authentication.</p>
      </div>
    );
  }

  const episodes = data?.episodes || [];
  const subscribedFeeds = data?.subscribed_feeds || 0;
  const totalEpisodes = data?.total || 0;

  return (
    <div className="h-full flex flex-col lg:flex-row gap-4">
      {/* Left Panel - Back link styled like feed list */}
      <div className="lg:w-80 flex-shrink-0 flex flex-col">
        <Link
          to="/podcasts"
          className="flex items-center gap-2 text-purple-600 hover:text-purple-800 mb-4 text-sm font-medium"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Back to Podcasts
        </Link>

        {/* Filter */}
        <div className="mb-4">
          <label className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/80 dark:bg-purple-950/50 border border-purple-200/50 dark:border-purple-700/30 cursor-pointer">
            <input
              type="checkbox"
              checked={showUnprocessedOnly}
              onChange={(e) => setShowUnprocessedOnly(e.target.checked)}
              className="rounded border-purple-300 text-purple-600 focus:ring-purple-500"
            />
            <span className="text-sm text-purple-700 dark:text-purple-300">Show unprocessed only</span>
          </label>
        </div>
      </div>

      {/* Right Panel - Episode list */}
      <div className="flex-1 flex flex-col min-w-0 bg-gradient-to-br from-purple-50/50 via-pink-50/30 to-cyan-50/50 dark:from-purple-950/30 dark:via-pink-950/20 dark:to-cyan-950/30 rounded-xl border border-purple-200/50 dark:border-purple-700/30 overflow-hidden">
        {/* Header */}
        <div className="p-4 sm:p-6 border-b border-purple-200/50 dark:border-purple-700/30 bg-white/50 dark:bg-purple-950/30">
          <div className="flex items-start gap-3">
            <img
              src="/images/logos/unicorn-logo.png"
              alt="Combined Feed"
              className="w-16 h-16 sm:w-20 sm:h-20 rounded-xl object-cover shadow-sm border border-purple-200/50 flex-shrink-0"
            />
            <div className="min-w-0 flex-1">
              <h2 className="text-xl sm:text-2xl font-bold text-purple-900 dark:text-purple-100 leading-tight">Combined Episodes</h2>
              <p className="text-purple-700 dark:text-purple-300 mt-1">All your subscriptions in one feed</p>
              <p className="text-xs sm:text-sm text-purple-500 dark:text-purple-400 mt-1">
                {subscribedFeeds} shows • {totalEpisodes} episodes
              </p>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 mt-4">
            <button
              onClick={handleCopyRss}
              className="px-3 py-2 text-sm font-medium text-white rounded-xl hover:shadow-lg hover:shadow-purple-500/30 transition-all flex items-center gap-2"
              style={{ background: 'linear-gradient(to right, #ec4899, #8b5cf6, #06b6d4)' }}
            >
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M6.18 15.64a2.18 2.18 0 0 1 2.18 2.18C8.36 19 7.38 20 6.18 20C5 20 4 19 4 17.82a2.18 2.18 0 0 1 2.18-2.18M4 4.44A15.56 15.56 0 0 1 19.56 20h-2.83A12.73 12.73 0 0 0 4 7.27V4.44m0 5.66a9.9 9.9 0 0 1 9.9 9.9h-2.83A7.07 7.07 0 0 0 4 12.93V10.1Z"/>
              </svg>
              Podly RSS
            </button>
            <button
              onClick={() => refetch()}
              className="px-3 py-2 text-sm font-medium rounded-xl transition-colors bg-white/80 dark:bg-purple-950/50 border border-purple-200/50 dark:border-purple-700/30 text-purple-700 dark:text-purple-300 hover:bg-purple-100 dark:hover:bg-purple-900/50"
            >
              Refresh
            </button>
          </div>
        </div>

        {/* Episodes List */}
        <div className="flex-1 overflow-y-auto p-4">
          {isLoading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-purple-600" />
            </div>
          ) : episodes.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-purple-500 dark:text-purple-400">
                {showUnprocessedOnly ? 'No unprocessed episodes' : 'No episodes found'}
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
                  className={`p-4 rounded-xl border transition-all ${
                    episode.has_processed_audio
                      ? 'bg-white/80 dark:bg-purple-950/50 border-purple-200/60 dark:border-purple-700/40 shadow-sm'
                      : episode.whitelisted
                      ? 'bg-white/80 dark:bg-purple-950/50 border-purple-200/60 dark:border-purple-700/40 shadow-sm'
                      : 'bg-purple-100/30 dark:bg-purple-950/30 border-purple-200/30 dark:border-purple-800/20 border-dashed'
                  }`}
                >
                  {/* Top row: Title + Status badge */}
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div className="flex-1 min-w-0">
                      <span className="text-left font-medium text-purple-900 dark:text-purple-100 line-clamp-2 leading-snug">
                        {episode.title}
                      </span>
                      <Link
                        to={`/podcasts?feed=${episode.feed_id}`}
                        className="text-sm text-purple-600 dark:text-purple-400 hover:underline block mt-0.5"
                      >
                        {episode.feed_title}
                      </Link>
                    </div>
                    {/* Status indicator */}
                    <div className="flex-shrink-0">
                      {episode.has_processed_audio ? (
                        <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400 rounded-lg">
                          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                          Ready
                        </span>
                      ) : episode.whitelisted ? (
                        <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400 rounded-lg">
                          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                          </svg>
                          Enabled
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium bg-purple-100/50 dark:bg-purple-900/30 text-purple-400 dark:text-purple-500 rounded-lg border border-dashed border-purple-300/50 dark:border-purple-700/50">
                          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                          </svg>
                          Disabled
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Middle row: Metadata */}
                  <div className="flex items-center gap-2 text-sm text-purple-400 dark:text-purple-500 mb-3">
                    <span>{formatDate(episode.release_date)}</span>
                    {episode.duration && (
                      <>
                        <span className="text-purple-200 dark:text-purple-600">•</span>
                        <span>{formatDuration(episode.duration)}</span>
                      </>
                    )}
                  </div>

                  {/* Bottom row: Actions - matching PodcastsPage style */}
                  <div className="flex flex-wrap items-center gap-1.5">
                    {/* Play button for processed episodes */}
                    {episode.has_processed_audio && (
                      <PlayButton episode={{
                        id: episode.id,
                        guid: episode.guid,
                        title: episode.title,
                        description: episode.description || '',
                        release_date: episode.release_date,
                        duration: episode.duration,
                        whitelisted: episode.whitelisted,
                        has_processed_audio: episode.has_processed_audio,
                        has_unprocessed_audio: true,
                        download_url: '',
                        image_url: episode.image_url,
                        download_count: 0,
                      }} />
                    )}

                    {/* Download button for processed episodes */}
                    {episode.has_processed_audio && (
                      <DownloadButton
                        episodeGuid={episode.guid}
                        isWhitelisted={episode.whitelisted}
                        hasProcessedAudio={episode.has_processed_audio}
                        feedId={episode.feed_id}
                      />
                    )}

                    {/* Process button for enabled but not yet processed */}
                    {episode.whitelisted && !episode.has_processed_audio && (
                      <button
                        onClick={() => processMutation.mutate(episode.guid)}
                        disabled={processMutation.isPending}
                        className="px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center gap-1 border bg-purple-600 border-purple-600 text-white hover:bg-purple-700 disabled:opacity-50"
                      >
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        Process
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
