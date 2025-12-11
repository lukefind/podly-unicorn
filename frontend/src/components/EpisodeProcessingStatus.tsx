import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { feedsApi } from '../services/api';

interface ProcessingStatus {
  status: string;
  step: number;
  step_name: string;
  total_steps: number;
  message: string;
  job_id?: string;
  download_url?: string;
  error?: string;
}

interface EpisodeProcessingStatusProps {
  episodeGuid: string;
  isWhitelisted: boolean;
  hasProcessedAudio: boolean;
  onProcessingComplete?: () => void;
}

const STEP_NAMES = ['Download', 'Transcribe', 'Detect Ads', 'Process Audio'];

export default function EpisodeProcessingStatus({
  episodeGuid,
  isWhitelisted,
  hasProcessedAudio,
  onProcessingComplete,
}: EpisodeProcessingStatusProps) {
  const [status, setStatus] = useState<ProcessingStatus | null>(null);

  // Poll for status updates
  useEffect(() => {
    if (!isWhitelisted || hasProcessedAudio) {
      setStatus(null);
      return;
    }

    let isMounted = true;
    let shouldPoll = true;

    const checkStatus = async () => {
      if (!shouldPoll) return;
      
      try {
        const response = await feedsApi.getPostStatus(episodeGuid);
        if (!isMounted) return;
        
        setStatus(response);

        // Check if we should keep polling
        if (response.status === 'completed' || response.status === 'skipped') {
          shouldPoll = false;
          onProcessingComplete?.();
        } else if (response.status === 'failed' || response.status === 'error') {
          shouldPoll = false;
        } else if (response.status === 'not_started') {
          shouldPoll = false;
          setStatus(null);
        }
        // Keep polling for 'running' or 'pending'
      } catch {
        // Keep polling on error - might be temporary
      }
    };

    // Initial check
    checkStatus();

    // Set up polling interval - always poll initially, then stop based on status
    const interval = setInterval(checkStatus, 2000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [episodeGuid, isWhitelisted, hasProcessedAudio, onProcessingComplete]);

  // Don't show anything if not processing
  if (!status || status.status === 'not_started' || status.status === 'completed' || status.status === 'skipped') {
    return null;
  }

  const isActive = status.status === 'running' || status.status === 'pending';
  const isFailed = status.status === 'failed' || status.status === 'error';
  const progressPercent = status.total_steps > 0 ? (status.step / status.total_steps) * 100 : 0;

  return (
    <div className="mt-3 p-3 rounded-lg bg-purple-50 border border-purple-100">
      {/* Header with status and job link */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {isActive && (
            <div className="w-3 h-3 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
          )}
          {isFailed && (
            <svg className="w-4 h-4 text-red-500" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
          )}
          <span className={`text-xs font-medium ${isFailed ? 'text-red-600' : 'text-purple-700'}`}>
            {status.status === 'pending' ? 'Queued' : status.status === 'running' ? 'Processing' : status.status}
          </span>
        </div>
        
        {status.job_id && (
          <Link
            to={`/jobs?job=${status.job_id}`}
            className="text-xs text-purple-500 hover:text-purple-700 hover:underline flex items-center gap-1"
          >
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
            View Job
          </Link>
        )}
      </div>

      {/* Progress bar */}
      {isActive && (
        <div className="mb-2">
          <div className="w-full bg-purple-100 rounded-full h-1.5">
            <div
              className="h-1.5 rounded-full bg-gradient-to-r from-pink-500 via-purple-500 to-cyan-500 transition-all duration-300"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      )}

      {/* Step indicators */}
      {isActive && (
        <div className="flex justify-between gap-1">
          {STEP_NAMES.map((name, index) => {
            const stepNum = index + 1;
            const isCompleted = status.step > stepNum;
            const isCurrent = status.step === stepNum;
            
            return (
              <div
                key={name}
                className={`flex-1 text-center py-1 px-1 rounded text-xs ${
                  isCompleted
                    ? 'bg-emerald-100 text-emerald-700'
                    : isCurrent
                    ? 'bg-purple-200 text-purple-800 font-medium'
                    : 'bg-purple-50 text-purple-400'
                }`}
              >
                <div className="flex items-center justify-center gap-1">
                  {isCompleted && (
                    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  )}
                  {isCurrent && (
                    <div className="w-2 h-2 border border-purple-600 border-t-transparent rounded-full animate-spin" />
                  )}
                  <span className="hidden sm:inline">{name}</span>
                  <span className="sm:hidden">{stepNum}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Current step name */}
      {isActive && status.step_name && (
        <div className="mt-2 text-xs text-purple-600 text-center">
          {status.step_name}
        </div>
      )}

      {/* Error message */}
      {isFailed && status.error && (
        <div className="mt-1 text-xs text-red-600">
          {status.error}
        </div>
      )}
    </div>
  );
}
