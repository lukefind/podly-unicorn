/**
 * Presentational component for processing progress UI.
 * This is the canonical progress display used across the app.
 * 
 * Usage:
 * - EpisodeProcessingStatus.tsx uses this with polling via feedsApi
 * - TriggerPage.tsx uses this with polling via /api/trigger/status
 */

interface ProcessingProgressUIProps {
  status: 'pending' | 'running' | 'completed' | 'failed' | 'error' | 'skipped';
  step: number;
  stepName: string;
  totalSteps: number;
  jobId?: string;
  error?: string;
  /** If provided, renders as an anchor tag. Otherwise uses react-router Link */
  jobLinkHref?: string;
}

const STEP_NAMES = ['Download', 'Transcribe', 'Detect Ads', 'Process Audio'];

export default function ProcessingProgressUI({
  status,
  step,
  stepName,
  totalSteps,
  jobId,
  error,
  jobLinkHref,
}: ProcessingProgressUIProps) {
  const isActive = status === 'running' || status === 'pending';
  const isFailed = status === 'failed' || status === 'error';
  const progressPercent = totalSteps > 0 ? (step / totalSteps) * 100 : 0;

  return (
    <div className="p-4 rounded-lg bg-purple-50 dark:bg-purple-900/30 border border-purple-100 dark:border-purple-700">
      {/* Header with status and job link */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {isActive && (
            <div className="w-4 h-4 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
          )}
          {isFailed && (
            <svg className="w-5 h-5 text-red-500" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
          )}
          {status === 'completed' && (
            <svg className="w-5 h-5 text-emerald-500" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
          )}
          <span className={`text-sm font-medium ${
            isFailed ? 'text-red-600 dark:text-red-400' : 
            status === 'completed' ? 'text-emerald-600 dark:text-emerald-400' : 
            'text-purple-700 dark:text-purple-300'
          }`}>
            {status === 'pending' ? 'Queued' : 
             status === 'running' ? 'Processing' : 
             status === 'completed' ? 'Complete' :
             status === 'failed' ? 'Failed' :
             status}
          </span>
        </div>
        
        {jobId && jobLinkHref && (
          <a
            href={jobLinkHref}
            className="text-xs text-purple-500 dark:text-purple-400 hover:text-purple-700 dark:hover:text-purple-300 hover:underline flex items-center gap-1"
          >
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
            View Job
          </a>
        )}
      </div>

      {/* Progress bar */}
      {isActive && (
        <div className="mb-3">
          <div className="w-full bg-purple-100 dark:bg-purple-800 rounded-full h-2">
            <div
              className="h-2 rounded-full bg-gradient-to-r from-pink-500 via-purple-500 to-cyan-500 transition-all duration-300"
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
            const isCompleted = step > stepNum;
            const isCurrent = step === stepNum;
            
            return (
              <div
                key={name}
                className={`flex-1 text-center py-1.5 px-1 rounded text-xs ${
                  isCompleted
                    ? 'bg-emerald-100 dark:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300'
                    : isCurrent
                    ? 'bg-purple-200 dark:bg-purple-700 text-purple-800 dark:text-purple-200 font-medium'
                    : 'bg-purple-50 dark:bg-purple-800/50 text-purple-400 dark:text-purple-500'
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
      {isActive && stepName && (
        <div className="mt-3 text-sm text-purple-600 dark:text-purple-300 text-center">
          {stepName}
        </div>
      )}

      {/* Error message */}
      {isFailed && error && (
        <div className="mt-2 text-sm text-red-600 dark:text-red-400">
          {error}
        </div>
      )}
    </div>
  );
}

export { STEP_NAMES };
export type { ProcessingProgressUIProps };
