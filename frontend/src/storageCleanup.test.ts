import { describe, expect, it } from 'vitest';
import type { CombinedConfig } from './types';

import {
  MAX_GLOBAL_RETENTION_DAYS,
  cleanupDispatchMessage,
  globalCleanupExplanation,
  normalizeStorageCleanupConfig,
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
    expect(toGlobalRetentionDays(true, MAX_GLOBAL_RETENTION_DAYS)).toBe(
      MAX_GLOBAL_RETENTION_DAYS,
    );
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

  it('rejects day counts above the shared frontend maximum', () => {
    expect(() =>
      toGlobalRetentionDays(true, MAX_GLOBAL_RETENTION_DAYS + 1),
    ).toThrow('maximum 36,500');
  });
});

describe('normalizeStorageCleanupConfig', () => {
  const configWithRetention = (retentionDays: number | null): CombinedConfig =>
    ({ app: { post_cleanup_retention_days: retentionDays } }) as CombinedConfig;

  it.each([0, -1, MAX_GLOBAL_RETENTION_DAYS + 1])(
    'normalizes legacy retention value %s to disabled',
    (retentionDays) => {
      const original = configWithRetention(retentionDays);
      const normalized = normalizeStorageCleanupConfig(original);

      expect(normalized.app.post_cleanup_retention_days).toBeNull();
      expect(original.app.post_cleanup_retention_days).toBe(retentionDays);
    },
  );

  it.each([null, 1, MAX_GLOBAL_RETENTION_DAYS])(
    'preserves supported retention value %s',
    (retentionDays) => {
      const original = configWithRetention(retentionDays);

      expect(
        normalizeStorageCleanupConfig(original).app.post_cleanup_retention_days,
      ).toBe(retentionDays);
    },
  );
});

describe('cleanupDispatchMessage', () => {
  it.each([
    ['queued', 'Cleanup was queued and will run shortly.'],
    ['coalesced', 'Cleanup is already queued or running.'],
    [
      'scheduler_disabled',
      'Automatic cleanup is disabled on this server; enable the scheduler or run maintenance from an external process.',
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
