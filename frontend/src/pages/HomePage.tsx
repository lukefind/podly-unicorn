import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { feedsApi, configApi } from '../services/api';
import FeedList from '../components/FeedList';
import FeedDetail from '../components/FeedDetail';
import AddFeedForm from '../components/AddFeedForm';
import type { Feed, ConfigResponse } from '../types';
import { toast } from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';

export default function HomePage() {
  const [showAddForm, setShowAddForm] = useState(false);
  const [selectedFeed, setSelectedFeed] = useState<Feed | null>(null);
  const { requireAuth, user } = useAuth();

  const { data: feeds, isLoading, error, refetch } = useQuery({
    queryKey: ['feeds'],
    queryFn: feedsApi.getFeeds,
  });

  useQuery<ConfigResponse>({
    queryKey: ['config'],
    queryFn: configApi.getConfig,
    enabled: !requireAuth || user?.role === 'admin',
  });
  const refreshAllMutation = useMutation({
    mutationFn: () => feedsApi.refreshAllFeeds(),
    onSuccess: (data) => {
      toast.success(
        `Refreshed ${data.feeds_refreshed} feeds and enqueued ${data.jobs_enqueued} jobs`
      );
      refetch();
    },
    onError: (err) => {
      console.error('Failed to refresh all feeds', err);
      toast.error('Failed to refresh all feeds');
    },
  });

  useEffect(() => {
    if (!showAddForm || typeof document === 'undefined') {
      return;
    }

    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = originalOverflow;
    };
  }, [showAddForm]);

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-md p-4">
        <p className="text-red-800">Error loading feeds. Please try again.</p>
      </div>
    );
  }


  return (
    <div className="h-full flex flex-col lg:flex-row gap-6">
      {/* Left Panel - Feed List (hidden on mobile when feed is selected) */}
      <div className={`flex-1 lg:max-w-md xl:max-w-lg flex flex-col ${
        selectedFeed ? 'hidden lg:flex' : 'flex'
      }`}>
        <div className="flex justify-between items-center mb-6 gap-3">
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold text-gray-900">Podcast Feeds</h2>
            <a
              href="https://t.me/+AV5-w_GSd2VjNjBk"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-[#229ED9] bg-[#229ED9]/10 rounded-full hover:bg-[#229ED9]/20 transition-colors"
              title="Join our Telegram community"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/>
              </svg>
              Community
            </a>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => refreshAllMutation.mutate()}
              disabled={refreshAllMutation.isPending}
              title="Refresh all feeds"
              className={`flex items-center justify-center px-3 py-2 rounded-md border transition-colors ${
                refreshAllMutation.isPending
                  ? 'border-purple-200 bg-purple-50 text-purple-400 cursor-not-allowed'
                  : 'border-purple-200 bg-purple-50 text-purple-600 hover:bg-purple-100'
              }`}
            >
              <svg 
                className={`w-4 h-4 ${refreshAllMutation.isPending ? 'animate-spin' : ''}`} 
                fill="none" 
                stroke="currentColor" 
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
            <button
              onClick={() => setShowAddForm((prev) => !prev)}
              className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-md font-medium transition-colors"
            >
              {showAddForm ? 'Close' : 'Add Feed'}
            </button>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-hidden">
          <FeedList 
            feeds={feeds || []} 
            onFeedDeleted={refetch}
            onFeedSelected={setSelectedFeed}
            selectedFeedId={selectedFeed?.id}
          />
        </div>
      </div>

      {/* Right Panel - Feed Detail */}
      {selectedFeed && (
        <div className={`flex-1 lg:flex-[2] ${
          selectedFeed ? 'flex' : 'hidden lg:flex'
        } flex-col bg-white rounded-lg shadow border overflow-hidden`}>
          <FeedDetail 
            feed={selectedFeed} 
            onClose={() => setSelectedFeed(null)}
            onFeedDeleted={() => {
              setSelectedFeed(null);
              refetch();
            }}
          />
        </div>
      )}

      {/* Empty State for Desktop */}
      {!selectedFeed && (
        <div className="hidden lg:flex flex-[2] items-center justify-center bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
          <div className="text-center">
            <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
            </svg>
            <h3 className="mt-2 text-sm font-medium text-gray-900">No podcast selected</h3>
            <p className="mt-1 text-sm text-gray-500">Select a podcast from the list to view details and episodes.</p>
          </div>
        </div>
      )}

      {showAddForm && (
        <div
          className="fixed inset-0 z-50 flex items-start sm:items-center justify-center bg-black/80 p-4 sm:p-6"
          onClick={() => setShowAddForm(false)}
        >
          <div
            className="w-full max-w-3xl bg-white rounded-2xl shadow-2xl border border-gray-200 flex flex-col max-h-[90vh]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-gray-200 px-4 sm:px-6 py-4">
              <div>
                <h2 className="text-xl sm:text-2xl font-semibold text-gray-900">Add a Podcast Feed</h2>
                <p className="text-sm text-gray-500 mt-1">
                  Paste an RSS URL or search the catalog to find shows to follow.
                </p>
              </div>
              <button
                onClick={() => setShowAddForm(false)}
                className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100 transition-colors"
                aria-label="Close add feed modal"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="overflow-y-auto px-4 sm:px-6 py-4">
              <AddFeedForm
                onSuccess={() => {
                  setShowAddForm(false);
                  refetch();
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
} 
