import { useState, useEffect, useRef } from 'react';
import { feedsApi } from '../services/api';
import type { PodcastSearchResult } from '../types';
import { useAuth } from '../contexts/AuthContext';
import { useEscapeKey } from '../hooks/useEscapeKey';
import { useTheme } from '../contexts/ThemeContext';

// Debounce hook for live search
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
}

interface AddFeedFormProps {
  onSuccess: () => void;
  subscribedFeedUrls?: string[];
}

type AddMode = 'url' | 'search';

const PAGE_SIZE = 10;

export default function AddFeedForm({ onSuccess, subscribedFeedUrls = [] }: AddFeedFormProps) {
  const [url, setUrl] = useState('');
  const [activeMode, setActiveMode] = useState<AddMode>('search');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [addingFeedUrl, setAddingFeedUrl] = useState<string | null>(null);
  const [addingPrivately, setAddingPrivately] = useState(false);
  const { requireAuth } = useAuth();
  const { theme } = useTheme();
  const isOriginal = theme === 'original';

  // Normalize URLs for comparison (remove trailing slashes, lowercase)
  const normalizeUrl = (url: string) => url.toLowerCase().replace(/\/+$/, '');
  const subscribedUrlsSet = new Set(subscribedFeedUrls.map(normalizeUrl));
  const isSubscribed = (feedUrl: string) => subscribedUrlsSet.has(normalizeUrl(feedUrl));

  const [searchTerm, setSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState<PodcastSearchResult[]>([]);
  const [searchError, setSearchError] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchPage, setSearchPage] = useState(1);
  const [totalResults, setTotalResults] = useState(0);
  const [previewPodcast, setPreviewPodcast] = useState<PodcastSearchResult | null>(null);
  useEscapeKey(!!previewPodcast, () => setPreviewPodcast(null));
  
  const searchInputRef = useRef<HTMLInputElement>(null);
  const debouncedSearchTerm = useDebounce(searchTerm, 400);

  const resetSearchState = () => {
    setSearchResults([]);
    setSearchError('');
    setSearchPage(1);
    setTotalResults(0);
  };

  // Auto-focus search input when in search mode
  useEffect(() => {
    if (activeMode === 'search' && searchInputRef.current) {
      // Longer delay for iOS to ensure modal is fully rendered
      // iOS Safari needs the element to be visible before focus works
      setTimeout(() => {
        if (searchInputRef.current) {
          searchInputRef.current.focus();
          // iOS workaround: scroll into view to help trigger keyboard
          searchInputRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }, 300);
    }
  }, [activeMode]);

  // Live search as user types (debounced)
  useEffect(() => {
    if (debouncedSearchTerm.trim().length >= 2) {
      performSearch();
    } else if (debouncedSearchTerm.trim().length === 0) {
      resetSearchState();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearchTerm]);

  const handleSubmitManual = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;

    setError('');
    await addFeed(url.trim(), 'url');
  };

  const addFeed = async (feedUrl: string, source: AddMode, isPrivate: boolean = false) => {
    setIsSubmitting(true);
    setAddingFeedUrl(source === 'url' ? 'manual' : feedUrl);
    setAddingPrivately(isPrivate);
    setError('');

    try {
      // Add the feed first
      const result = await feedsApi.addFeed(feedUrl);
      
      // If auth is enabled and user wants private subscription, update it
      if (requireAuth && isPrivate && result.feed_id) {
        await feedsApi.subscribeFeed(result.feed_id, true);
      }
      
      if (source === 'url') {
        setUrl('');
      }
      onSuccess();
    } catch (err) {
      console.error('Failed to add feed:', err);
      setError('Failed to add feed. Please check the URL and try again.');
    } finally {
      setIsSubmitting(false);
      setAddingFeedUrl(null);
      setAddingPrivately(false);
    }
  };

  const performSearch = async () => {
    if (!searchTerm.trim()) {
      setSearchError('Enter a search term to find podcasts.');
      return;
    }

    setIsSearching(true);
    setSearchError('');

    try {
      const response = await feedsApi.searchFeeds(searchTerm.trim());
      setSearchResults(response.results);
      setTotalResults(response.total ?? response.results.length);
      setSearchPage(1);
    } catch (err) {
      console.error('Podcast search failed:', err);
      setSearchError('Failed to search podcasts. Please try again.');
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  };


  const handleAddFromSearch = async (result: PodcastSearchResult, isPrivate: boolean = false) => {
    await addFeed(result.feedUrl, 'search', isPrivate);
  };

  const totalPages =
    totalResults === 0 ? 1 : Math.max(1, Math.ceil(totalResults / PAGE_SIZE));
  const startIndex =
    totalResults === 0 ? 0 : (searchPage - 1) * PAGE_SIZE + 1;
  const endIndex =
    totalResults === 0
      ? 0
      : Math.min(searchPage * PAGE_SIZE, totalResults);
  const displayedResults = searchResults.slice(
    (searchPage - 1) * PAGE_SIZE,
    (searchPage - 1) * PAGE_SIZE + PAGE_SIZE
  );

  return (
    <div className="flex flex-col h-full">
      <div className={`flex gap-1 mb-3 rounded-lg p-0.5 ${isOriginal ? 'bg-blue-900/50' : 'bg-gray-100 dark:bg-gray-700/50'}`}>
        <button
          type="button"
          onClick={() => {
            setActiveMode('search');
            setError('');
            resetSearchState();
          }}
          className={`flex-1 px-2 py-1.5 text-sm rounded-md transition-colors ${
            activeMode === 'search'
              ? isOriginal
                ? 'bg-blue-600 text-white shadow-sm font-medium'
                : 'bg-white dark:bg-gray-600 text-gray-900 dark:text-gray-100 shadow-sm font-medium'
              : isOriginal
                ? 'text-blue-200 hover:text-white'
                : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
          }`}
        >
          Search
        </button>
        <button
          type="button"
          onClick={() => {
            setActiveMode('url');
          }}
          className={`flex-1 px-2 py-1.5 text-sm rounded-md transition-colors ${
            activeMode === 'url'
              ? isOriginal
                ? 'bg-blue-600 text-white shadow-sm font-medium'
                : 'bg-white dark:bg-gray-600 text-gray-900 dark:text-gray-100 shadow-sm font-medium'
              : isOriginal
                ? 'text-blue-200 hover:text-white'
                : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
          }`}
        >
          RSS URL
        </button>
      </div>

      {activeMode === 'url' && (
        <form onSubmit={handleSubmitManual} className="space-y-4">
          <div>
            <label htmlFor="feed-url" className={`block text-sm font-medium mb-1 ${isOriginal ? 'text-blue-200' : 'text-gray-700'}`}>
              RSS Feed URL
            </label>
            <input
              type="url"
              id="feed-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/podcast/feed.xml"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent ${
                isOriginal
                  ? 'bg-blue-950/60 border-blue-400/30 text-blue-100 placeholder-blue-300/40'
                  : 'border-gray-300 bg-white'
              }`}
              required
            />
          </div>

          {error && (
            <div className="text-red-600 text-sm">{error}</div>
          )}

          <div className="flex flex-col sm:flex-row sm:justify-end gap-3">
            <button
              type="submit"
              disabled={isSubmitting || !url.trim()}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white px-4 py-2 rounded-md font-medium transition-colors sm:w-auto w-full"
            >
              {isSubmitting && addingFeedUrl === 'manual' ? 'Adding...' : 'Add Feed'}
            </button>
          </div>
        </form>
      )}

      {activeMode === 'search' && !previewPodcast && (
        <div className="flex flex-col flex-1 min-h-0 gap-2">
          <div className="flex gap-2">
            <input
              ref={searchInputRef}
              type="text"
              id="search-term"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search podcasts..."
              className={`flex-1 px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent ${
                isOriginal
                  ? 'bg-blue-950/60 border-blue-400/30 text-blue-100 placeholder-blue-300/40'
                  : 'border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100'
              }`}
              autoComplete="off"
            />
            {isSearching && (
              <div className="flex items-center px-2">
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600" />
              </div>
            )}
          </div>

          {searchError && (
            <div className="text-red-600 text-sm">{searchError}</div>
          )}

          {isSearching && searchResults.length === 0 && (
            <div className="text-sm text-gray-600">Searching for podcasts...</div>
          )}

          {!isSearching && searchResults.length === 0 && totalResults === 0 && searchTerm && !searchError && (
            <div className="text-sm text-gray-600">No podcasts found. Try a different search term.</div>
          )}

          {searchResults.length > 0 && (
            <div className="flex flex-col flex-1 min-h-0">
              <div className="flex justify-between items-center text-xs text-gray-400 dark:text-gray-500 mb-1">
                <span>{startIndex}-{endIndex} of {totalResults}</span>
                <div className="flex gap-1">
                  <button
                    type="button"
                    onClick={() =>
                      setSearchPage((prev) => Math.max(prev - 1, 1))
                    }
                    disabled={isSearching || searchPage <= 1}
                    className="px-2 py-0.5 text-xs rounded disabled:text-gray-300 dark:disabled:text-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                  >
                    Prev
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setSearchPage((prev) => Math.min(prev + 1, totalPages))
                    }
                    disabled={isSearching || searchPage >= totalPages}
                    className="px-2 py-0.5 text-xs rounded disabled:text-gray-300 dark:disabled:text-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                  >
                    Next
                  </button>
                </div>
              </div>

              <ul className="flex-1 overflow-y-auto -mx-3 sm:-mx-4">
                {displayedResults.map((result, idx) => (
                  <li
                    key={result.feedUrl}
                    className={`hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors cursor-pointer ${
                      idx > 0 ? 'border-t border-gray-100 dark:border-gray-700/50' : ''
                    }`}
                    onClick={() => setPreviewPodcast(result)}
                  >
                    <div className="flex items-center gap-3 px-3 sm:px-4 py-2.5">
                      {result.artworkUrl ? (
                        <img
                          src={result.artworkUrl}
                          alt={result.title}
                          className="w-11 h-11 sm:w-14 sm:h-14 rounded-lg object-cover flex-shrink-0"
                        />
                      ) : (
                        <div className="w-11 h-11 sm:w-14 sm:h-14 rounded-lg bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-gray-400 text-xs flex-shrink-0">
                          No Art
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <h4 className="font-medium text-gray-900 dark:text-gray-100 text-sm line-clamp-1">{result.title}</h4>
                        {result.author && (
                          <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{result.author}</p>
                        )}
                        {result.genres.length > 0 && (
                          <p className="text-xs text-gray-400 dark:text-gray-500 truncate">
                            {result.genres.join(' · ')}
                          </p>
                        )}
                      </div>
                      <svg className="w-4 h-4 text-gray-300 dark:text-gray-600 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Inline podcast detail view (replaces search list) */}
      {activeMode === 'search' && previewPodcast && (
        <div className="flex flex-col flex-1 min-h-0">
          {/* Back button */}
          <button
            type="button"
            onClick={() => setPreviewPodcast(null)}
            className="flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 mb-3 self-start"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            Back to results
          </button>

          {/* Podcast header */}
          <div className="flex gap-4 mb-4">
            {previewPodcast.artworkUrl ? (
              <img
                src={previewPodcast.artworkUrl}
                alt={previewPodcast.title}
                className="w-24 h-24 rounded-lg object-cover flex-shrink-0 shadow-sm"
              />
            ) : (
              <div className="w-24 h-24 rounded-lg bg-gray-200 flex items-center justify-center text-gray-500 text-xs flex-shrink-0">
                No Image
              </div>
            )}
            <div className="flex-1 min-w-0">
              <h3 className="font-semibold text-gray-900 text-lg leading-tight">
                {previewPodcast.title}
              </h3>
              {previewPodcast.author && (
                <p className="text-sm text-gray-600 mt-1">{previewPodcast.author}</p>
              )}
              {previewPodcast.genres.length > 0 && (
                <p className="text-xs text-gray-500 mt-1">
                  {previewPodcast.genres.join(' · ')}
                </p>
              )}
              <p className="text-xs text-gray-400 mt-1.5 truncate">{previewPodcast.feedUrl}</p>
            </div>
          </div>

          {/* Subscribe actions */}
          <div className="flex items-center gap-2 mb-4 pb-4 border-b border-gray-200">
            {isSubscribed(previewPodcast.feedUrl) ? (
              <span className="inline-flex items-center gap-1.5 px-4 py-2 bg-green-100 text-green-700 rounded-lg text-sm font-medium">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Subscribed
              </span>
            ) : requireAuth ? (
              <>
                <button
                  type="button"
                  onClick={() => handleAddFromSearch(previewPodcast, false)}
                  disabled={isSubmitting && addingFeedUrl === previewPodcast.feedUrl}
                  className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white px-4 py-2 rounded-l-lg text-sm font-medium transition-colors"
                  title="Subscribe publicly"
                >
                  {isSubmitting && addingFeedUrl === previewPodcast.feedUrl && !addingPrivately ? 'Subscribing...' : 'Subscribe'}
                </button>
                <button
                  type="button"
                  onClick={() => handleAddFromSearch(previewPodcast, true)}
                  disabled={isSubmitting && addingFeedUrl === previewPodcast.feedUrl}
                  className="bg-gray-500 hover:bg-gray-600 disabled:bg-gray-400 text-white px-2 py-2 rounded-r-lg text-sm transition-colors"
                  title="Subscribe privately"
                >
                  {isSubmitting && addingFeedUrl === previewPodcast.feedUrl && addingPrivately ? (
                    <span className="px-1">...</span>
                  ) : (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                    </svg>
                  )}
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => handleAddFromSearch(previewPodcast)}
                disabled={isSubmitting && addingFeedUrl === previewPodcast.feedUrl}
                className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
              >
                {isSubmitting && addingFeedUrl === previewPodcast.feedUrl ? 'Adding...' : 'Add Podcast'}
              </button>
            )}
          </div>

          {/* Description */}
          <div className="flex-1 overflow-y-auto">
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Description</h4>
            {previewPodcast.description ? (
              <p className="text-sm text-gray-700 whitespace-pre-line leading-relaxed">
                {previewPodcast.description}
              </p>
            ) : (
              <p className="text-sm text-gray-400 italic">No description available.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
