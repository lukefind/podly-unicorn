import { useCallback, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQueryClient } from '@tanstack/react-query';
import { feedsApi } from '../services/api';
import { useEscapeKey } from '../hooks/useEscapeKey';
import { useTheme } from '../contexts/ThemeContext';

interface ReprocessButtonProps {
  episodeGuid: string;
  isWhitelisted: boolean;
  feedId?: number;
  className?: string;
  onReprocessStart?: () => void;
}

export default function ReprocessButton({
  episodeGuid,
  isWhitelisted,
  feedId,
  className = '',
  onReprocessStart
}: ReprocessButtonProps) {
  const { theme } = useTheme();
  const isOriginal = theme === 'original';
  const [isReprocessing, setIsReprocessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const queryClient = useQueryClient();
  const closeModal = useCallback(() => setShowModal(false), []);

  useEscapeKey(showModal, closeModal);

  const handleReprocessClick = async () => {
    if (!isWhitelisted) {
      setError('Post must be whitelisted before reprocessing');
      return;
    }

    setShowModal(true);
  };

  const handleConfirmReprocess = async () => {
    closeModal();
    setIsReprocessing(true);
    setError(null);

    try {
      const response = await feedsApi.reprocessPost(episodeGuid);

      if (response.status === 'started') {
        // Notify parent component that reprocessing started
        onReprocessStart?.();

        // Invalidate queries to refresh the UI
        if (feedId) {
          queryClient.invalidateQueries({ queryKey: ['episodes', feedId] });
        }
        queryClient.invalidateQueries({ queryKey: ['episode-stats', episodeGuid] });
      } else {
        setError(response.message || 'Failed to start reprocessing');
      }
    } catch (err: unknown) {
      console.error('Error starting reprocessing:', err);
      const errorMessage = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { message?: string } } }).response?.data?.message || 'Failed to start reprocessing'
        : 'Failed to start reprocessing';
      setError(errorMessage);
    } finally {
      setIsReprocessing(false);
    }
  };

  if (!isWhitelisted) {
    return null;
  }

  return (
    <div className={`${className}`}>
      <button
        onClick={handleReprocessClick}
        disabled={isReprocessing}
        className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all border flex items-center gap-1.5 ${
          isReprocessing
            ? isOriginal
              ? 'bg-amber-500 text-white cursor-wait border-amber-400'
              : 'bg-orange-500 text-white cursor-wait border-orange-500'
            : isOriginal
              ? 'bg-blue-950/60 border-amber-300/55 text-amber-100 hover:bg-blue-900/70 hover:border-amber-200/70'
              : 'bg-white border-orange-200 text-orange-600 hover:bg-orange-50'
        }`}
        title={
          isReprocessing
            ? 'Clearing data and reprocessing...'
            : 'Clear all processing data and start fresh processing'
        }
      >
        {isReprocessing ? (
          <>
            <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
            Reprocessing...
          </>
        ) : (
          <>
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Reprocess
          </>
        )}
      </button>

      {error && (
        <div className="text-xs text-red-600 mt-1">
          {error}
        </div>
      )}

      {/* Confirmation Modal - rendered via portal to document.body */}
      {showModal && createPortal(
        <div 
          className="fixed inset-0 flex items-center justify-center p-4"
          style={{
            zIndex: 9999,
            backgroundColor: isOriginal ? 'rgba(2, 8, 23, 0.78)' : 'rgba(88, 28, 135, 0.6)',
            backdropFilter: isOriginal ? 'none' : 'blur(2px)',
          }}
          onClick={closeModal}
        >
          <div 
            className="modal-content bg-white rounded-2xl max-w-md w-full overflow-hidden shadow-2xl border border-purple-200"
            style={isOriginal ? { backgroundColor: '#0b234d', borderColor: 'rgba(96, 165, 250, 0.45)' } : undefined}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div
              className="flex items-center justify-between p-6 border-b border-purple-100 bg-gradient-to-r from-pink-50 via-purple-50 to-cyan-50"
              style={isOriginal ? { borderColor: 'rgba(96, 165, 250, 0.32)', background: 'linear-gradient(to right, #123867, #1b4f87, #123867)' } : undefined}
            >
              <h2 className={`text-xl font-bold ${isOriginal ? 'text-blue-100' : 'text-purple-900'}`}>Confirm Reprocess</h2>
              <button
                onClick={closeModal}
                className={`p-2 rounded-lg transition-colors ${isOriginal ? 'text-blue-200 hover:text-blue-50 hover:bg-blue-800/45' : 'text-purple-400 hover:text-purple-600 hover:bg-purple-100'}`}
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Content */}
            <div className="p-6">
              <p className={`mb-6 ${isOriginal ? 'text-blue-100' : 'text-purple-800'}`}>
                Are you sure you want to reprocess this episode? This will delete the existing processed data and start fresh processing.
              </p>

              {/* Action Buttons */}
              <div className="flex gap-3 justify-end">
                <button
                  onClick={closeModal}
                  className={`px-4 py-2 text-sm font-medium rounded-xl transition-colors ${
                    isOriginal
                      ? 'text-blue-100 bg-blue-900/50 border border-blue-300/45 hover:bg-blue-800/60'
                      : 'text-purple-700 bg-white border border-purple-200 hover:bg-purple-50'
                  }`}
                >
                  Cancel
                </button>
                <button
                  onClick={handleConfirmReprocess}
                  className={`px-4 py-2 text-sm font-medium text-white rounded-xl transition-all ${
                    isOriginal
                      ? 'bg-blue-500 hover:bg-blue-400 border border-blue-300/55'
                      : 'bg-gradient-to-r from-pink-500 via-purple-500 to-cyan-500 hover:shadow-lg hover:shadow-purple-500/30'
                  }`}
                >
                  Reprocess Episode
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}
