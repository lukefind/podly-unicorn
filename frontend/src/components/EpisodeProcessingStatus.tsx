import { useState, useEffect } from 'react';
import { feedsApi } from '../services/api';
import ProcessingProgressUI from './ProcessingProgressUI';

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
  pollTrigger?: number;
}

export default function EpisodeProcessingStatus({
  episodeGuid,
  isWhitelisted: _isWhitelisted,
  hasProcessedAudio,
  onProcessingComplete,
  pollTrigger,
}: EpisodeProcessingStatusProps) {
  const [status, setStatus] = useState<ProcessingStatus | null>(null);

  // Poll for status updates - ONLY when explicitly triggered by pollTrigger
  // This prevents polling for all whitelisted episodes (which would cause thousands of requests)
  useEffect(() => {
    // Only poll if:
    // 1. pollTrigger is set (user clicked Process button), OR
    // 2. We already have a status showing processing in progress
    const shouldStartPolling = pollTrigger || (status && (status.status === 'pending' || status.status === 'running'));
    
    if (!shouldStartPolling) {
      return;
    }

    // Don't poll if already processed (unless just triggered)
    if (hasProcessedAudio && !pollTrigger) {
      setStatus(null);
      return;
    }

    let isMounted = true;
    let shouldPoll = true;
    const pollStartedAt = Date.now();

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
          setStatus(null);
          // If the user just triggered processing, the backend may briefly report
          // 'not_started' while the job is enqueued. Keep polling for a short grace period.
          if (pollTrigger && Date.now() - pollStartedAt < 15000) {
            return;
          }
          shouldPoll = false;
        }
        // Keep polling for 'running' or 'pending'
      } catch {
        // Keep polling on error - might be temporary
      }
    };

    // Initial check
    checkStatus();

    // Set up polling interval
    const interval = setInterval(checkStatus, 2000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [episodeGuid, hasProcessedAudio, onProcessingComplete, pollTrigger, status]);

  // Don't show anything if not processing
  if (!status || status.status === 'not_started' || status.status === 'completed' || status.status === 'skipped') {
    return null;
  }

  return (
    <div className="mt-3">
      <ProcessingProgressUI
        status={status.status as 'pending' | 'running' | 'completed' | 'failed' | 'error' | 'skipped'}
        step={status.step}
        stepName={status.step_name}
        totalSteps={status.total_steps}
        jobId={status.job_id}
        error={status.error}
      />
    </div>
  );
}
