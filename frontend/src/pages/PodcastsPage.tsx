import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { createPortal } from 'react-dom';
import { feedsApi } from '../services/api';
import { toast } from 'react-hot-toast';
import type { Feed, Episode } from '../types';
import AddFeedForm from '../components/AddFeedForm';
import DownloadButton from '../components/DownloadButton';
import PlayButton from '../components/PlayButton';
import ProcessingStatsButton from '../components/ProcessingStatsButton';
import ReprocessButton from '../components/ReprocessButton';
import ProcessButton from '../components/ProcessButton';
import EpisodeProcessingStatus from '../components/EpisodeProcessingStatus';
import { useAuth } from '../contexts/AuthContext';

export default function PodcastsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [showAddForm, setShowAddForm] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [showMenu, setShowMenu] = useState(false);
  const [showSubscriptions, setShowSubscriptions] = useState(false);
  const [showHelpModal, setShowHelpModal] = useState(false);
  const { requireAuth } = useAuth();

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

  // Auto-select first feed if none selected and feeds are loaded
  useEffect(() => {
    if (!selectedFeedId && feedsArray.length > 0 && !feedsLoading) {
      setSearchParams({ feed: feedsArray[0].id.toString() });
    }
  }, [feedsArray, selectedFeedId, feedsLoading, setSearchParams]);

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

  // Subscription mutations for the feed list
  const togglePrivacyMutation = useMutation({
    mutationFn: ({ feedId, isPrivate }: { feedId: number; isPrivate: boolean }) => 
      feedsApi.subscribeFeed(feedId, isPrivate),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
    },
  });

  const unsubscribeMutation = useMutation({
    mutationFn: (feedId: number) => feedsApi.unsubscribeFeed(feedId),
    onSuccess: () => {
      toast.success('Unsubscribed');
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      queryClient.invalidateQueries({ queryKey: ['all-feeds'] });
      handleCloseFeed();
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
        
        {requireAuth && (
          <button
            onClick={() => setShowSubscriptions(true)}
            className="w-full mb-4 px-3 py-2 bg-purple-50 text-purple-700 text-sm font-medium rounded-lg hover:bg-purple-100 transition-colors border border-purple-200 flex items-center justify-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            Browse Podcasts on Server
          </button>
        )}

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
              {requireAuth && (
                <button
                  onClick={() => setShowSubscriptions(true)}
                  className="mt-3 px-4 py-2 bg-purple-100 text-purple-700 text-sm font-medium rounded-lg hover:bg-purple-200 transition-colors"
                >
                  Browse Podcasts on Server
                </button>
              )}
            </div>
          ) : (
            filteredFeeds.map((feed: Feed) => (
              <div
                key={feed.id}
                className={`p-3 rounded-lg transition-all ${
                  selectedFeedId === feed.id
                    ? 'bg-purple-100 dark:bg-purple-900/40 border-2 border-purple-500'
                    : 'bg-white/80 dark:bg-purple-950/50 border border-purple-200/50 dark:border-purple-700/30 hover:border-purple-300 dark:hover:border-purple-600/50 hover:shadow-sm'
                }`}
              >
                <div 
                  className="flex items-center gap-3 cursor-pointer"
                  onClick={() => handleSelectFeed(feed)}
                >
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
                {/* Subscription controls - only show when auth is enabled */}
                {requireAuth && (
                  <div className="flex items-center justify-end gap-2 mt-2 pt-2 border-t border-purple-100/50">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        togglePrivacyMutation.mutate({ feedId: feed.id, isPrivate: !(feed as any).is_private });
                      }}
                      disabled={togglePrivacyMutation.isPending}
                      className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs transition-colors ${
                        (feed as any).is_private
                          ? 'bg-gray-200 text-gray-600'
                          : 'bg-green-100 text-green-700'
                      }`}
                      title={(feed as any).is_private 
                        ? 'Private - This feed is hidden from other users. Click to make public.' 
                        : 'Public - Other users can discover this feed. Click to make private.'}
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        {(feed as any).is_private ? (
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                        ) : (
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                        )}
                      </svg>
                      {(feed as any).is_private ? 'Private' : 'Public'}
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm('Unsubscribe from this podcast?')) {
                          unsubscribeMutation.mutate(feed.id);
                        }
                      }}
                      disabled={unsubscribeMutation.isPending}
                      className="px-2 py-1 rounded text-xs bg-red-50 text-red-600 hover:bg-red-100 transition-colors"
                      title="Unsubscribe from this podcast"
                    >
                      Unsubscribe
                    </button>
                  </div>
                )}
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
                onClick={async () => {
                  try {
                    // Try to get authenticated share link first
                    const shareData = await feedsApi.getFeedShareLink(selectedFeed.id);
                    navigator.clipboard.writeText(shareData.url);
                    toast.success('RSS URL copied to clipboard!');
                  } catch {
                    // If auth is disabled or error, use simple URL
                    const rssUrl = `${window.location.origin}/feed/${selectedFeed.id}`;
                    navigator.clipboard.writeText(rssUrl);
                    toast.success('RSS URL copied to clipboard!');
                  }
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
                          setShowHelpModal(true);
                          setShowMenu(false);
                        }}
                        className="w-full px-4 py-2 text-sm text-left flex items-center gap-3 hover:bg-purple-50 transition-colors"
                        style={{ color: '#6b7280' }}
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        How processing works
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
                      episode.whitelisted || episode.has_processed_audio
                        ? 'bg-white/80 dark:bg-purple-950/50 border-purple-200/60 dark:border-purple-700/40 shadow-sm'
                        : 'bg-purple-100/30 dark:bg-purple-950/30 border-purple-200/30 dark:border-purple-800/20 border-dashed'
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
                          <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium bg-blue-100 text-blue-700 rounded-lg">
                            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
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
                            Disable
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
                        <ProcessButton 
                          episodeGuid={episode.guid}
                          feedId={selectedFeed?.id}
                        />
                      )}

                      {/* Reprocess button for already processed episodes */}
                      {episode.has_processed_audio && (
                        <ReprocessButton 
                          episodeGuid={episode.guid}
                          isWhitelisted={episode.whitelisted}
                          feedId={selectedFeed?.id}
                        />
                      )}
                    </div>

                    {/* Processing status indicator */}
                    <EpisodeProcessingStatus
                      episodeGuid={episode.guid}
                      isWhitelisted={episode.whitelisted}
                      hasProcessedAudio={episode.has_processed_audio}
                      onProcessingComplete={() => {
                        queryClient.invalidateQueries({ queryKey: ['episodes', selectedFeed?.id] });
                      }}
                    />
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

      {/* Subscription Management Modal */}
      {showSubscriptions && createPortal(
        <SubscriptionModal 
          onClose={() => setShowSubscriptions(false)} 
          onUpdate={() => refetchFeeds()}
        />,
        document.body
      )}

      {/* Help Modal - How Processing Works */}
      {showHelpModal && createPortal(
        <div 
          className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
          style={{ zIndex: 9999 }}
          onClick={() => setShowHelpModal(false)}
        >
          <div 
            className="bg-white rounded-2xl max-w-lg w-full overflow-hidden shadow-2xl border border-purple-200"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b border-purple-100 bg-gradient-to-r from-pink-50 via-purple-50 to-cyan-50">
              <h2 className="text-xl font-bold text-purple-900">How Processing Works</h2>
              <button
                onClick={() => setShowHelpModal(false)}
                className="p-2 text-purple-400 hover:text-purple-600 rounded-lg hover:bg-purple-100 transition-colors"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Content */}
            <div className="p-6 space-y-4">
              <div className="flex gap-3">
                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center">
                  <svg className="w-4 h-4 text-blue-600" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                </div>
                <div>
                  <h3 className="font-semibold text-purple-900">Enabled</h3>
                  <p className="text-sm text-purple-700">Episode is eligible for ad removal. Click "Process" to start, or it will process automatically when your podcast app requests it.</p>
                </div>
              </div>

              <div className="flex gap-3">
                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-purple-100 flex items-center justify-center">
                  <svg className="w-4 h-4 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                  </svg>
                </div>
                <div>
                  <h3 className="font-semibold text-purple-900">Disabled</h3>
                  <p className="text-sm text-purple-700">Episode is skipped entirely. It won't be processed and won't appear in your podcast app's Podly feed.</p>
                </div>
              </div>

              <div className="flex gap-3">
                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center">
                  <svg className="w-4 h-4 text-emerald-600" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                  </svg>
                </div>
                <div>
                  <h3 className="font-semibold text-purple-900">Ready</h3>
                  <p className="text-sm text-purple-700">Episode has been processed and ads removed. You can play, download, or view stats.</p>
                </div>
              </div>

              <div className="mt-4 p-4 bg-purple-50 rounded-xl border border-purple-100">
                <p className="text-sm text-purple-800">
                  <strong>💡 Tip:</strong> Processing happens on-demand, not automatically. This saves resources and API costs. Enable episodes you want, then either click "Process" or let your podcast app trigger it when you subscribe to the Podly RSS feed.
                </p>
              </div>
            </div>

            {/* Footer */}
            <div className="p-4 border-t border-purple-100 bg-purple-50/50">
              <button
                onClick={() => setShowHelpModal(false)}
                className="w-full px-4 py-2 text-sm font-medium text-white bg-gradient-to-r from-pink-500 via-purple-500 to-cyan-500 rounded-xl hover:shadow-lg hover:shadow-purple-500/30 transition-all"
              >
                Got it!
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

// Subscription Management Modal Component
function SubscriptionModal({ onClose, onUpdate }: { onClose: () => void; onUpdate: () => void }) {
  const queryClient = useQueryClient();
  
  const { data: allFeeds, isLoading } = useQuery({
    queryKey: ['all-feeds'],
    queryFn: feedsApi.getAllFeeds,
  });

  const subscribeMutation = useMutation({
    mutationFn: ({ feedId, isPrivate }: { feedId: number; isPrivate: boolean }) => 
      feedsApi.subscribeFeed(feedId, isPrivate),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['all-feeds'] });
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      queryClient.invalidateQueries({ queryKey: ['episodes', variables.feedId] });
      onUpdate();
    },
  });

  const unsubscribeMutation = useMutation({
    mutationFn: (feedId: number) => feedsApi.unsubscribeFeed(feedId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['all-feeds'] });
      queryClient.invalidateQueries({ queryKey: ['feeds'] });
      onUpdate();
    },
  });

  const handleSubscribe = (feedId: number, isPrivate: boolean = false) => {
    subscribeMutation.mutate({ feedId, isPrivate });
  };

  const handleUnsubscribe = (feedId: number) => {
    unsubscribeMutation.mutate(feedId);
  };

  const handleTogglePrivacy = (feedId: number, currentPrivacy: boolean) => {
    // Re-subscribe with toggled privacy
    subscribeMutation.mutate({ feedId, isPrivate: !currentPrivacy });
  };

  return (
    <div 
      className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
      style={{ zIndex: 9999 }}
      onClick={onClose}
    >
      <div 
        className="w-full max-w-2xl bg-white rounded-2xl shadow-2xl border border-gray-200 flex flex-col max-h-[80vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">Manage Subscriptions</h2>
            <p className="text-sm text-gray-500 mt-1">Choose which podcasts appear in your feed list</p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        
        <div className="overflow-y-auto px-6 py-4 flex-1">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-600" />
            </div>
          ) : allFeeds && allFeeds.length > 0 ? (
            <div className="space-y-3">
              {allFeeds.map((feed) => (
                <div 
                  key={feed.id}
                  className={`flex items-center gap-4 p-4 rounded-xl border transition-all ${
                    feed.is_subscribed 
                      ? 'bg-purple-50 border-purple-200' 
                      : 'bg-gray-50 border-gray-200'
                  }`}
                >
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
                  <div className="flex items-center gap-2">
                    {feed.is_subscribed ? (
                      <>
                        {/* Privacy indicator and toggle */}
                        <button
                          onClick={() => handleTogglePrivacy(feed.id, (feed as any).is_private || false)}
                          disabled={subscribeMutation.isPending}
                          className={`p-2 rounded-lg transition-colors ${
                            (feed as any).is_private
                              ? 'bg-gray-700 text-white'
                              : 'bg-gray-100 text-gray-400 hover:bg-gray-200'
                          }`}
                          title={(feed as any).is_private 
                            ? 'Private subscription - This feed won\'t appear in "Browse Podcasts" for other users. Click to make public.' 
                            : 'Public subscription - Other users can see this feed in "Browse Podcasts". Click to make private.'}
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            {(feed as any).is_private ? (
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                            ) : (
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                            )}
                          </svg>
                        </button>
                        <button
                          onClick={() => handleUnsubscribe(feed.id)}
                          disabled={unsubscribeMutation.isPending}
                          className="px-4 py-2 text-sm font-medium rounded-lg bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50"
                          title="Click to unsubscribe from this feed"
                        >
                          Subscribed
                        </button>
                      </>
                    ) : (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => handleSubscribe(feed.id, false)}
                          disabled={subscribeMutation.isPending}
                          className="px-3 py-2 text-sm font-medium rounded-l-lg bg-gray-200 text-gray-700 hover:bg-gray-300 disabled:opacity-50"
                          title="Subscribe publicly - other users will see this feed in Browse Podcasts"
                        >
                          Subscribe
                        </button>
                        <button
                          onClick={() => handleSubscribe(feed.id, true)}
                          disabled={subscribeMutation.isPending}
                          className="px-2 py-2 text-sm font-medium rounded-r-lg bg-gray-300 text-gray-600 hover:bg-gray-400 disabled:opacity-50"
                          title="Subscribe privately - this feed won't appear in Browse Podcasts for other users"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                          </svg>
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8">
              <p className="text-gray-500">No podcasts available</p>
              <p className="text-sm text-gray-400 mt-1">Ask an admin to add some podcasts first</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
