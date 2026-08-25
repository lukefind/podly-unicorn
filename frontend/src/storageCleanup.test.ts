import { describe, expect, it } from 'vitest';

import {
  cleanupDispatchMessage,
  globalCleanupExplanation,
  toGlobalRetentionDays,
} from './storageCleanup';

describe('toGlobalRetentionDays', () => {
  it('maps a disabled global age policy to null', () => {
    expect(toGlobalRetentionDays(false, undefined)).toBeNull();
    expect(toGlobalRetentionDays(false, 14)).toBeNull();
  });

  it('returns a positive integer day count when enabled', () => {
    expect(toGlobalRetentionDays(true, 14)).toBe(14);
    expect(toGlobalRetentionDays(true, '14')).toBe(14);
  });

  it.each([undefined, null, 0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY])(
    'rejects invalid enabled day count %s',
    (days) => {
      expect(() => toGlobalRetentionDays(true, days)).toThrow(
        'Enter a positive whole number of days',
      );
    },
  );

  it.each(['', '0', '-1', '1.5', '1e3', '14abc'])(
    'rejects malformed enabled day input %s',
    (days) => {
      expect(() => toGlobalRetentionDays(true, days)).toThrow(
        'Enter a positive whole number of days',
      );
    },
  );
});

describe('cleanupDispatchMessage', () => {
  it.each([
    ['queued', 'Cleanup was queued and will run shortly.'],
    ['coalesced', 'Cleanup was added to the maintenance run already in progress.'],
    [
      'scheduler_disabled',
      'Automatic cleanup is disabled on this server; run maintenance manually or externally.',
    ],
    ['not_requested', 'No cleanup run was needed.'],
  ] as const)('describes the %s dispatch state', (status, expected) => {
    expect(cleanupDispatchMessage({ requested: status !== 'not_requested', status })).toBe(
      expected,
    );
  });
});

describe('globalCleanupExplanation', () => {
  it('explains maintenance that continues while global age cleanup is off', () => {
    const explanation = globalCleanupExplanation(false);

    expect(explanation).toContain('Per-feed episode limits still apply');
    expect(explanation).toContain('orphaned job files');
  });

  it('explains feed overrides and metadata preservation when enabled', () => {
    const explanation = globalCleanupExplanation(true);

    expect(explanation).toContain('per-feed count limits override');
    expect(explanation).toContain('Episode metadata is preserved');
  });
});
