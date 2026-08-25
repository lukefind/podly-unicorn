import { cleanupDispatchMessage } from './storageCleanup';
import type { CleanupDispatch, EffectiveCleanupPolicy } from './types';

export const FEED_RETENTION_COUNT_MAX = 10_000;

export type FeedCleanupMode = 'inherit' | 'count';

const INVALID_COUNT_MESSAGE =
  `Enter a whole number between 1 and ${FEED_RETENTION_COUNT_MAX}.`;

export function toFeedRetentionCount(
  mode: FeedCleanupMode,
  count: unknown,
): number | null {
  if (mode === 'inherit') {
    return null;
  }

  const parsedCount =
    typeof count === 'string' && /^[1-9]\d*$/.test(count.trim())
      ? Number(count.trim())
      : count;
  if (
    !Number.isSafeInteger(parsedCount) ||
    (parsedCount as number) <= 0 ||
    (parsedCount as number) > FEED_RETENTION_COUNT_MAX
  ) {
    throw new Error(INVALID_COUNT_MESSAGE);
  }
  return parsedCount as number;
}

export function initialFeedCleanupMode(
  configuredCount: number | null | undefined,
): FeedCleanupMode {
  return configuredCount == null ? 'inherit' : 'count';
}

export function describeEffectiveCleanupPolicy(
  policy: EffectiveCleanupPolicy | undefined,
): string {
  if (!policy) {
    return 'The current effective cleanup policy is unavailable.';
  }
  if (policy.type === 'count') {
    return `Keeping the newest ${policy.retention_count} successfully processed episodes for this feed.`;
  }
  if (policy.type === 'age') {
    return `Inheriting the global policy: processed episode files older than ${policy.retention_days} days can be removed.`;
  }
  if (policy.source === 'feed') {
    return (
      `Per-feed episode cleanup is disabled because the stored value ` +
      `(${policy.retention_count}) is an invalid per-feed count. Safe orphan maintenance remains active.`
    );
  }
  return (
    'Inheriting the global policy: global age cleanup is disabled. ' +
    'Safe orphan maintenance remains active.'
  );
}

export function describeGlobalFeedPolicy(
  retentionDays: number | null | undefined,
): string {
  if (retentionDays == null) {
    return 'Global policy: age-based episode cleanup is disabled; orphan maintenance still runs.';
  }
  return `Global policy: remove processed episode files older than ${retentionDays} days.`;
}

export function feedCleanupSaveMessage(
  retentionCount: number | null,
  dispatch: CleanupDispatch,
): string {
  const policyMessage =
    retentionCount === null
      ? 'Policy saved: inherit the global cleanup policy.'
      : `Policy saved: keep the newest ${retentionCount} successfully processed episodes.`;
  return `${policyMessage} ${cleanupDispatchMessage(dispatch)}`;
}
