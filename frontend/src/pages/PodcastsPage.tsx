import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { feedsApi } from '../services/api';
import { toast } from 'react-hot-toast';
import type { Feed, Episode } from '../types';
import AddFeedForm from '../components/AddFeedForm';
import DownloadButton from '../components/DownloadButton';
import PlayButton from '../components/PlayButton';
import ProcessingStatsButton from '../components/ProcessingStatsButton';
import ReprocessButton from '../components/ReprocessButton';

export default function PodcastsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [showAddForm, setShowAddForm] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [showMenu, setShowMenu] = useState(false);

  // Get selected feed from URL
  const selectedFeedId = searchParams.get('feed') ? parseInt(searchParams.get('feed')!) : null;

  const { data: feeds, isLoading: feedsLoading, refetch: refetchFeeds } = useQuery({
    queryKey: ['feeds'],
    queryFn: feedsApi.getFeeds,
  });

  const { data: episodes, isLoading: episodesLoading } = useQuery({
    queryKey: ['episodes', selectedFeedId],
    queryFn: () => feedsApi.getFeedPosts(selectedFeedId!),
    enabled: !!selectedFeedId,
  });

  const feedsArray = Array.isArray(feeds) ? feeds : [];
  const selectedFeed = feedsArray.find((f: Feed) => f.id === selectedFeedId);

  const filteredFeeds = feedsArray.filter((feed: Feed) => {
    if (!searchTerm) return true;
    const term = searchTerm.toLowerCase();
    return feed.title?.toLowerCase().includes(term) || feed.author?.toLowerCase().includes(term);
  });

  const handleSelectFeed = (feed: Feed) => {
    setSearchParams({ feed: feed.id.toString() });
  };

  const handleCloseFeed = () => {
    setSearchParams({});
  };

  const deleteFeedMutation = useMutation({
    mutationFn: (feedId: number) => feedsApi.deleteFeed(feedId),
    onSuccess: () => {
      toast.success('Feed deleted');
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      handleCloseFeed();
    },
    onError: () => {
      toast.error('Failed to delete feed');
    },
  });

  const refreshFeedMutation = useMutation({
    mutationFn: (feedId: number) => feedsApi.refreshFeed(feedId),
    onSuccess: (data) => {
      toast.success(data?.message ?? 'Feed refreshed');
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      queryClient.invalidateQueries({ queryKey: ['episodes', selectedFeedId] });
    },
    onError: () => {
      toast.error('Failed to refresh feed');
    },
  });

  const whitelistMutation = useMutation({
    mutationFn: ({ guid, whitelisted }: { guid: string; whitelisted: boolean }) =>
      feedsApi.togglePostWhitelist(guid, whitelisted),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['episodes', selectedFeedId] });
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

  if (feedsLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    );
  }

  return (
    <div className="h-full flex gap-6">
      {/* Left Panel - Feed List */}
      <div className={`w-80 flex-shrink-0 flex flex-col ${selectedFeed ? 'hidden lg:flex' : 'flex'}`}>
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-xl font-bold text-gray-900">Podcasts</h1>
          <button
            onClick={() => setShowAddForm(true)}
            className="px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
          >
            + Add
          </button>
        </div>

        <input
          type="search"
          placeholder="Search podcasts..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full px-3 py-2 mb-4 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        />

        <div className="flex-1 overflow-y-auto space-y-2">
          {filteredFeeds.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-gray-500">No podcasts found</p>
            </div>
          ) : (
            filteredFeeds.map((feed: Feed) => (
              <div
                key={feed.id}
                onClick={() => handleSelectFeed(feed)}
                className={`p-3 rounded-lg cursor-pointer transition-all ${
                  selectedFeedId === feed.id
                    ? 'bg-blue-50 border-2 border-blue-500'
                    : 'bg-white border border-gray-200 hover:border-gray-300 hover:shadow-sm'
                }`}
              >
                <div className="flex items-center gap-3">
                  {feed.image_url ? (
                    <img
                      src={feed.image_url}
                      alt={feed.title}
                      className="w-12 h-12 rounded-lg object-cover"
                    />
                  ) : (
                    <div className="w-12 h-12 rounded-lg bg-gray-200 flex items-center justify-center">
                      <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                      </svg>
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-gray-900 truncate">{feed.title}</h3>
                    <p className="text-xs text-gray-500">{feed.posts_count} episodes</p>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Right Panel - Feed Detail */}
      {selectedFeed ? (
        <div className="flex-1 flex flex-col bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 shadow-sm overflow-hidden">
          {/* Feed Header */}
          <div className="p-6 border-b border-purple-100/50 bg-gradient-to-r from-pink-50/50 via-purple-50/50 to-cyan-50/50">
            <div className="flex items-start gap-4">
              <button
                onClick={handleCloseFeed}
                className="lg:hidden p-2 -ml-2 text-purple-500 hover:text-purple-700"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
              {selectedFeed.image_url && (
                <img
                  src={selectedFeed.image_url}
                  alt={selectedFeed.title}
                  className="w-20 h-20 rounded-xl object-cover shadow-md"
                />
              )}
              <div className="flex-1">
                <h2 className="text-xl font-bold text-purple-900">{selectedFeed.title}</h2>
                {selectedFeed.author && (
                  <p className="text-purple-600 mt-1">by {selectedFeed.author}</p>
                )}
                <p className="text-sm text-purple-500 mt-1">{selectedFeed.posts_count} episodes</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => refreshFeedMutation.mutate(selectedFeed.id)}
                  disabled={refreshFeedMutation.isPending}
                  className="p-2 text-purple-500 hover:text-purple-700 hover:bg-purple-100 rounded-xl transition-colors"
                  title="Refresh feed"
                >
                  <svg className={`w-5 h-5 ${refreshFeedMutation.isPending ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                </button>
                <button
                  onClick={() => {
                    if (confirm(`Delete "${selectedFeed.title}"?`)) {
                      deleteFeedMutation.mutate(selectedFeed.id);
                    }
                  }}
                  className="p-2 text-pink-500 hover:text-pink-700 hover:bg-pink-50 rounded-xl transition-colors"
                  title="Delete feed"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>

            {/* Subscribe Button & Actions */}
            <div className="flex flex-wrap items-center gap-3 mt-4">
              <button
                onClick={() => {
                  const rssUrl = `${window.location.origin}/api/feeds/${selectedFeed.id}/rss`;
                  navigator.clipboard.writeText(rssUrl);
                  toast.success('RSS URL copied to clipboard!');
                }}
                className="px-4 py-2 text-sm font-medium text-white bg-gradient-to-r from-pink-500 via-purple-500 to-cyan-500 rounded-xl hover:shadow-lg hover:shadow-purple-500/30 transition-all flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M6.18 15.64a2.18 2.18 0 0 1 2.18 2.18C8.36 19 7.38 20 6.18 20C5 20 4 19 4 17.82a2.18 2.18 0 0 1 2.18-2.18M4 4.44A15.56 15.56 0 0 1 19.56 20h-2.83A12.73 12.73 0 0 0 4 7.27V4.44m0 5.66a9.9 9.9 0 0 1 9.9 9.9h-2.83A7.07 7.07 0 0 0 4 12.93V10.1Z"/>
                </svg>
                Subscribe to Podly RSS
              </button>
              <button
                onClick={() => refreshFeedMutation.mutate(selectedFeed.id)}
                disabled={refreshFeedMutation.isPending}
                className="px-4 py-2 text-sm font-medium text-purple-700 bg-white/80 border border-purple-200 rounded-xl hover:bg-purple-50 transition-colors flex items-center gap-2"
              >
                <svg className={`w-4 h-4 ${refreshFeedMutation.isPending ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Refresh Feed
              </button>
              <a
                href={selectedFeed.rss_url}
                target="_blank"
                rel="noopener noreferrer"
                className="px-4 py-2 text-sm font-medium text-purple-700 bg-white/80 border border-purple-200 rounded-xl hover:bg-purple-50 transition-colors flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M6.18 15.64a2.18 2.18 0 0 1 2.18 2.18C8.36 19 7.38 20 6.18 20C5 20 4 19 4 17.82a2.18 2.18 0 0 1 2.18-2.18M4 4.44A15.56 15.56 0 0 1 19.56 20h-2.83A12.73 12.73 0 0 0 4 7.27V4.44m0 5.66a9.9 9.9 0 0 1 9.9 9.9h-2.83A7.07 7.07 0 0 0 4 12.93V10.1Z"/>
                </svg>
                Original RSS
              </a>

              {/* More Options Menu */}
              <div className="relative">
                <button
                  onClick={() => setShowMenu(!showMenu)}
                  className="p-2 text-purple-700 bg-white/80 border border-purple-200 rounded-xl hover:bg-purple-50 transition-colors"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
                  </svg>
                </button>
                
                {showMenu && (
                  <div className="absolute right-0 mt-2 w-56 rounded-xl shadow-lg border border-purple-200 overflow-hidden" style={{ backgroundColor: '#ffffff', zIndex: 50 }}>
                    <div className="py-1">
                      <button
                        onClick={() => {
                          // Enable all episodes
                          episodes?.forEach((ep: Episode) => {
                            if (!ep.whitelisted) {
                              whitelistMutation.mutate({ guid: ep.guid, whitelisted: true });
                            }
                          });
                          setShowMenu(false);
                          toast.success('All episodes enabled');
                        }}
                        className="w-full px-4 py-2 text-sm text-left flex items-center gap-3 hover:bg-purple-50 transition-colors"
                        style={{ color: '#059669' }}
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                        Enable all episodes
                      </button>
                      <button
                        onClick={() => {
                          // Disable all episodes
                          episodes?.forEach((ep: Episode) => {
                            if (ep.whitelisted) {
                              whitelistMutation.mutate({ guid: ep.guid, whitelisted: false });
                            }
                          });
                          setShowMenu(false);
                          toast.success('All episodes disabled');
                        }}
                        className="w-full px-4 py-2 text-sm text-left flex items-center gap-3 hover:bg-purple-50 transition-colors"
                        style={{ color: '#dc2626' }}
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                        </svg>
                        Disable all episodes
                      </button>
                      <div className="border-t border-purple-100 my-1" />
                      <button
                        onClick={() => {
                          toast(
                            'Enabled = eligible for processing when requested by your podcast app or manually. Disabled = skipped entirely. Processing happens on-demand, not automatically.',
                            { duration: 8000 }
                          );
                          setShowMenu(false);
                        }}
                        className="w-full px-4 py-2 text-sm text-left flex items-center gap-3 hover:bg-purple-50 transition-colors"
                        style={{ color: '#6b7280' }}
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        Explain enable/disable
                      </button>
                      <div className="border-t border-purple-100 my-1" />
                      <button
                        onClick={() => {
                          if (confirm(`Delete "${selectedFeed.title}"? This cannot be undone.`)) {
                            deleteFeedMutation.mutate(selectedFeed.id);
                          }
                          setShowMenu(false);
                        }}
                        className="w-full px-4 py-2 text-sm text-left flex items-center gap-3 hover:bg-red-50 transition-colors"
                        style={{ color: '#dc2626' }}
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                        Delete feed
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Description */}
            {selectedFeed.description && (
              <p className="mt-4 text-sm text-purple-700 line-clamp-3">{selectedFeed.description}</p>
            )}
          </div>

          {/* Episodes List */}
          <div className="flex-1 overflow-y-auto p-4">
            {episodesLoading ? (
              <div className="flex items-center justify-center h-32">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600" />
              </div>
            ) : episodes && episodes.length > 0 ? (
              <div className="space-y-3">
                {episodes.map((episode: Episode) => (
                  <div
                    key={episode.id}
                    className={`p-4 rounded-xl border transition-all ${
                      episode.whitelisted
                        ? 'bg-white border-purple-200/60 shadow-sm'
                        : 'bg-purple-50/30 border-purple-100/40 opacity-60'
                    }`}
                  >
                    {/* Top row: Title + Status badge */}
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <div className="flex-1 min-w-0">
                        <h3 className="font-medium text-purple-900 line-clamp-2 leading-snug">{episode.title}</h3>
                      </div>
                      {/* Status indicator */}
                      <div className="flex-shrink-0">
                        {episode.has_processed_audio ? (
                          <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium bg-emerald-100 text-emerald-700 rounded-lg">
                            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                            </svg>
                            Ready
                          </span>
                        ) : episode.whitelisted ? (
                          <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium bg-amber-100 text-amber-700 rounded-lg">
                            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
                            </svg>
                            Pending
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium bg-gray-100 text-gray-500 rounded-lg">
                            Skipped
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Middle row: Metadata */}
                    <div className="flex items-center gap-2 text-sm text-purple-400 mb-3">
                      <span>{formatDate(episode.release_date)}</span>
                      <span className="text-purple-200">•</span>
                      {episode.duration && <span>{formatDuration(episode.duration)}</span>}
                    </div>

                    {/* Bottom row: Actions - uniform button style */}
                    <div className="flex flex-wrap items-center gap-2">
                      {/* Toggle Enable/Skip */}
                      <button
                        onClick={() => whitelistMutation.mutate({ guid: episode.guid, whitelisted: !episode.whitelisted })}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 border ${
                          episode.whitelisted
                            ? 'bg-white border-red-200 text-red-600 hover:bg-red-50'
                            : 'bg-white border-emerald-200 text-emerald-600 hover:bg-emerald-50'
                        }`}
                      >
                        {episode.whitelisted ? (
                          <>
                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                            Skip
                          </>
                        ) : (
                          <>
                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                            </svg>
                            Enable
                          </>
                        )}
                      </button>

                      {/* Processed episode actions */}
                      {episode.has_processed_audio && (
                        <>
                          <PlayButton episode={episode} />
                          <DownloadButton 
                            episodeGuid={episode.guid}
                            isWhitelisted={episode.whitelisted}
                            hasProcessedAudio={episode.has_processed_audio}
                            feedId={selectedFeed?.id}
                          />
                          <ProcessingStatsButton 
                            episodeGuid={episode.guid}
                            hasProcessedAudio={episode.has_processed_audio}
                          />
                        </>
                      )}

                      {/* Process button for enabled but not yet processed */}
                      {episode.whitelisted && !episode.has_processed_audio && (
                        <ReprocessButton 
                          episodeGuid={episode.guid}
                          isWhitelisted={episode.whitelisted}
                          feedId={selectedFeed?.id}
                        />
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8">
                <p className="text-gray-500">No episodes found</p>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="flex-1 hidden lg:flex items-center justify-center bg-gray-50 rounded-xl border-2 border-dashed border-gray-300">
          <div className="text-center">
            <svg className="w-12 h-12 text-gray-400 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            </svg>
            <p className="text-gray-500">Select a podcast to view episodes</p>
          </div>
        </div>
      )}

      {/* Add Feed Modal */}
      {showAddForm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          onClick={() => setShowAddForm(false)}
        >
          <div
            className="w-full max-w-3xl bg-white rounded-2xl shadow-2xl border border-gray-200 flex flex-col max-h-[90vh]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <div>
                <h2 className="text-xl font-semibold text-gray-900">Add a Podcast Feed</h2>
                <p className="text-sm text-gray-500 mt-1">Paste an RSS URL or search the catalog</p>
              </div>
              <button
                onClick={() => setShowAddForm(false)}
                className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="overflow-y-auto px-6 py-4">
              <AddFeedForm
                onSuccess={() => {
                  setShowAddForm(false);
                  refetchFeeds();
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
