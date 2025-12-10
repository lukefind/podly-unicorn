import { useState } from 'react';
import { createPortal } from 'react-dom';
import { useQueryClient } from '@tanstack/react-query';
import { feedsApi } from '../services/api';

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
  const [isReprocessing, setIsReprocessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const queryClient = useQueryClient();

  const handleReprocessClick = async () => {
    if (!isWhitelisted) {
      setError('Post must be whitelisted before reprocessing');
      return;
    }

    setShowModal(true);
  };

  const handleConfirmReprocess = async () => {
    setShowModal(false);
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
            ? 'bg-orange-500 text-white cursor-wait border-orange-500'
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
          className="fixed inset-0 bg-purple-900/60 backdrop-blur-sm flex items-center justify-center p-4"
          style={{ zIndex: 9999 }}
          onClick={() => setShowModal(false)}
        >
          <div 
            className="bg-white rounded-2xl max-w-md w-full overflow-hidden shadow-2xl border border-purple-200"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b border-purple-100 bg-gradient-to-r from-pink-50 via-purple-50 to-cyan-50">
              <h2 className="text-xl font-bold text-purple-900">Confirm Reprocess</h2>
              <button
                onClick={() => setShowModal(false)}
                className="p-2 text-purple-400 hover:text-purple-600 rounded-lg hover:bg-purple-100 transition-colors"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Content */}
            <div className="p-6">
              <p className="text-purple-800 mb-6">
                Are you sure you want to reprocess this episode? This will delete the existing processed data and start fresh processing.
              </p>

              {/* Action Buttons */}
              <div className="flex gap-3 justify-end">
                <button
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 text-sm font-medium text-purple-700 bg-white border border-purple-200 rounded-xl hover:bg-purple-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleConfirmReprocess}
                  className="px-4 py-2 text-sm font-medium text-white bg-gradient-to-r from-pink-500 via-purple-500 to-cyan-500 rounded-xl hover:shadow-lg hover:shadow-purple-500/30 transition-all"
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
