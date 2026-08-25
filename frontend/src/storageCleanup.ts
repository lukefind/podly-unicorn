import type { CleanupDispatch } from './types';

const INVALID_DAYS_MESSAGE = 'Enter a positive whole number of days.';

export function toGlobalRetentionDays(
  enabled: boolean,
  days: unknown,
): number | null {
  if (!enabled) {
    return null;
  }

  const parsedDays =
    typeof days === 'string' && /^[1-9]\d*$/.test(days.trim())
      ? Number(days.trim())
      : days;
  if (!Number.isSafeInteger(parsedDays) || (parsedDays as number) <= 0) {
    throw new Error(INVALID_DAYS_MESSAGE);
  }
  return parsedDays as number;
}

export function cleanupDispatchMessage(dispatch: CleanupDispatch): string {
  switch (dispatch.status) {
    case 'queued':
      return 'Cleanup was queued and will run shortly.';
    case 'coalesced':
      return 'Cleanup was added to the maintenance run already in progress.';
    case 'scheduler_disabled':
      return 'Automatic cleanup is disabled on this server; run maintenance manually or externally.';
    case 'not_requested':
      return 'No cleanup run was needed.';
  }
}

export function globalCleanupExplanation(enabled: boolean): string {
  if (!enabled) {
    return (
      'Per-feed episode limits still apply while global age cleanup is off. ' +
      'Safe maintenance of orphaned job files also continues.'
    );
  }
  return (
    'Episodes older than this limit can have local processing files removed; ' +
    'per-feed count limits override this global policy. Episode metadata is preserved for reprocessing.'
  );
}
