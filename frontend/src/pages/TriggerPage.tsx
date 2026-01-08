/**
 * Trigger Page - Public page for processing episodes via feed token auth.
 * 
 * This page is accessed via RSS feed links and uses feed token authentication
 * (not session auth). It displays the canonical processing progress UI.
 * 
 * URL: /trigger?guid=X&token_id=Y&secret=Z
 */

import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import ProcessingProgressUI from '../components/ProcessingProgressUI';

interface TriggerStatus {
  state: 'ready' | 'processing' | 'queued' | 'failed' | 'not_found' | 'error' | 'not_started';
  processed: boolean;
  download_url: string | null;
  message: string;
  job: {
    id: string;
    status: string;
    current_step: number;
    total_steps: number;
    step_name: string;
    progress_percentage: number;
    error_message?: string;
  } | null;
}

export default function TriggerPage() {
  const [searchParams] = useSearchParams();
  const guid = searchParams.get('guid');
  const tokenId = searchParams.get('token_id') || searchParams.get('feed_token');
  const secret = searchParams.get('secret') || searchParams.get('feed_secret');

  const [status, setStatus] = useState<TriggerStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isInitialLoad, setIsInitialLoad] = useState(true);

  // Build status URL with cache buster
  const buildStatusUrl = useCallback(() => {
    if (!guid || !tokenId || !secret) return null;
    return `/api/trigger/status?guid=${encodeURIComponent(guid)}&feed_token=${encodeURIComponent(tokenId)}&feed_secret=${encodeURIComponent(secret)}&t=${Date.now()}`;
  }, [guid, tokenId, secret]);

  // Fetch status
  const fetchStatus = useCallback(async () => {
    const url = buildStatusUrl();
    if (!url) return;

    try {
      const response = await fetch(url, { cache: 'no-store' });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        setError(data.message || `Error: ${response.status}`);
        return;
      }

      const data: TriggerStatus = await response.json();
      setStatus(data);
      setError(null);

      // Extract episode info from first successful response
      if (isInitialLoad && data.message) {
        setIsInitialLoad(false);
      }
    } catch (err) {
      console.error('Failed to fetch trigger status:', err);
    }
  }, [buildStatusUrl, isInitialLoad]);

  // Initial trigger (start processing if needed)
  useEffect(() => {
    if (!guid || !tokenId || !secret) {
      setError('Missing required parameters: guid, token_id, secret');
      return;
    }

    // We're already on the trigger page, so just start polling
    fetchStatus();
  }, [guid, tokenId, secret, fetchStatus]);

  // Poll for status updates
  useEffect(() => {
    if (!guid || !tokenId || !secret) return;
    if (error) return;

    // Don't poll if already complete or failed
    if (status?.state === 'ready' || status?.state === 'failed') return;

    const interval = setInterval(fetchStatus, 2000);
    return () => clearInterval(interval);
  }, [guid, tokenId, secret, error, status?.state, fetchStatus]);

  // Adapt trigger status to ProcessingProgressUI props
  const getProgressProps = () => {
    if (!status?.job) {
      if (status?.state === 'ready') {
        return {
          status: 'completed' as const,
          step: 4,
          stepName: 'Complete',
          totalSteps: 4,
        };
      }
      if (status?.state === 'queued') {
        return {
          status: 'pending' as const,
          step: 0,
          stepName: 'Waiting in queue...',
          totalSteps: 4,
        };
      }
      return null;
    }

    return {
      status: (status.job.status === 'running' ? 'running' : 
               status.job.status === 'pending' ? 'pending' :
               status.job.status === 'completed' ? 'completed' :
               status.job.status === 'failed' ? 'failed' : 'pending') as 'running' | 'pending' | 'completed' | 'failed',
      step: status.job.current_step,
      stepName: status.job.step_name || `Step ${status.job.current_step}/${status.job.total_steps}`,
      totalSteps: status.job.total_steps,
      jobId: status.job.id,
      error: status.job.error_message,
    };
  };

  const progressProps = getProgressProps();

  // Missing params error
  if (!guid || !tokenId || !secret) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-purple-600 via-purple-700 to-indigo-800 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full overflow-hidden">
          <div className="bg-gradient-to-r from-purple-600 to-indigo-600 p-6 text-center">
            <h1 className="text-2xl font-bold text-white">Podly Unicorn</h1>
            <p className="text-purple-200 text-sm mt-1">Ad-free podcast processing</p>
          </div>
          <div className="p-6 text-center">
            <div className="text-4xl mb-4">&#9888;</div>
            <h2 className="text-xl font-semibold text-gray-800 mb-2">Invalid Link</h2>
            <p className="text-gray-600">This link is missing required parameters. Please use the link from your podcast app.</p>
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-purple-600 via-purple-700 to-indigo-800 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full overflow-hidden">
          <div className="bg-gradient-to-r from-purple-600 to-indigo-600 p-6 text-center">
            <h1 className="text-2xl font-bold text-white">Podly Unicorn</h1>
            <p className="text-purple-200 text-sm mt-1">Ad-free podcast processing</p>
          </div>
          <div className="p-6 text-center">
            <div className="text-4xl mb-4 text-red-500">&#10060;</div>
            <h2 className="text-xl font-semibold text-gray-800 mb-2">Error</h2>
            <p className="text-gray-600">{error}</p>
          </div>
        </div>
      </div>
    );
  }

  // Ready state - show download instructions
  if (status?.state === 'ready') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-purple-600 via-purple-700 to-indigo-800 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full overflow-hidden">
          <div className="bg-gradient-to-r from-purple-600 to-indigo-600 p-6 text-center">
            <h1 className="text-2xl font-bold text-white">Podly Unicorn</h1>
            <p className="text-purple-200 text-sm mt-1">Ad-free podcast processing</p>
          </div>
          <div className="p-6">
            <div className="text-center mb-6">
              <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8 text-emerald-600" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
              </div>
              <h2 className="text-xl font-semibold text-gray-800 mb-2">Episode Ready!</h2>
              <p className="text-gray-600">The ad-free version is ready to download.</p>
            </div>

            <div className="bg-purple-50 rounded-xl p-4 mb-4">
              <h3 className="font-medium text-purple-900 mb-2">Next steps:</h3>
              <ol className="text-sm text-purple-700 space-y-2">
                <li className="flex items-start gap-2">
                  <span className="bg-purple-200 text-purple-800 rounded-full w-5 h-5 flex items-center justify-center text-xs font-medium flex-shrink-0">1</span>
                  <span>Return to your podcast app</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="bg-purple-200 text-purple-800 rounded-full w-5 h-5 flex items-center justify-center text-xs font-medium flex-shrink-0">2</span>
                  <span>Download or stream the episode as normal</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="bg-purple-200 text-purple-800 rounded-full w-5 h-5 flex items-center justify-center text-xs font-medium flex-shrink-0">3</span>
                  <span>Enjoy your ad-free listening!</span>
                </li>
              </ol>
            </div>

            {status.download_url && (
              <a
                href={status.download_url}
                className="block w-full py-3 px-4 bg-gradient-to-r from-purple-600 to-indigo-600 text-white text-center font-medium rounded-xl hover:from-purple-700 hover:to-indigo-700 transition-all"
              >
                Download Now
              </a>
            )}
          </div>
        </div>
      </div>
    );
  }

  // Processing state
  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-600 via-purple-700 to-indigo-800 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full overflow-hidden">
        <div className="bg-gradient-to-r from-purple-600 to-indigo-600 p-6 text-center">
          <h1 className="text-2xl font-bold text-white">Podly Unicorn</h1>
          <p className="text-purple-200 text-sm mt-1">Ad-free podcast processing</p>
        </div>
        <div className="p-6">
          <div className="text-center mb-6">
            <h2 className="text-xl font-semibold text-gray-800 mb-2">
              {status?.state === 'queued' ? 'Queued for Processing' : 'Processing Episode'}
            </h2>
            <p className="text-gray-600 text-sm">
              {status?.message || 'Removing ads from your episode...'}
            </p>
          </div>

          {/* Canonical progress UI */}
          {progressProps && (
            <ProcessingProgressUI
              {...progressProps}
              jobLinkHref={progressProps.jobId ? `/jobs?job=${progressProps.jobId}` : undefined}
            />
          )}

          <div className="mt-6 text-center text-sm text-gray-500">
            <p>This page updates automatically.</p>
            <p className="mt-1">You can close this page and return later.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
