import { describe, expect, it } from 'vitest';

import type { CleanupDispatch, EffectiveCleanupPolicy } from './types';
import {
  FEED_RETENTION_COUNT_MAX,
  canManageFeedCleanup,
  describeEffectiveCleanupPolicy,
  describeGlobalFeedPolicy,
  feedCleanupSaveMessage,
  initialFeedCleanupMode,
  toFeedRetentionCount,
} from './feedCleanupPolicy';

describe('canManageFeedCleanup', () => {
  it('allows administrators and auth-disabled installations', () => {
    expect(canManageFeedCleanup(true, 'admin')).toBe(true);
    expect(canManageFeedCleanup(false, null)).toBe(true);
  });

  it('hides controls from authenticated regular users', () => {
    expect(canManageFeedCleanup(true, 'user')).toBe(false);
    expect(canManageFeedCleanup(true, null)).toBe(false);
  });
});

describe('toFeedRetentionCount', () => {
  it('maps inherit mode to the global policy regardless of the count input', () => {
    expect(toFeedRetentionCount('inherit', '')).toBeNull();
    expect(toFeedRetentionCount('inherit', 20)).toBeNull();
  });

  it('maps a positive whole-number count to newest processed episode retention', () => {
    expect(toFeedRetentionCount('count', 5)).toBe(5);
    expect(toFeedRetentionCount('count', '5')).toBe(5);
    expect(toFeedRetentionCount('count', `${FEED_RETENTION_COUNT_MAX}`)).toBe(
      FEED_RETENTION_COUNT_MAX,
    );
  });

  it.each([
    undefined,
    null,
    '',
    0,
    -1,
    1.5,
    '1.5',
    '1e3',
    true,
    FEED_RETENTION_COUNT_MAX + 1,
  ])('rejects invalid count mode input %s', (value) => {
    expect(() => toFeedRetentionCount('count', value)).toThrow(
      `Enter a whole number between 1 and ${FEED_RETENTION_COUNT_MAX}`,
    );
  });
});

describe('initialFeedCleanupMode', () => {
  it('uses inherit for null and count for a positive configured override', () => {
    expect(initialFeedCleanupMode(null)).toBe('inherit');
    expect(initialFeedCleanupMode(3)).toBe('count');
  });

  it('keeps an invalid stored override in count mode so it is not mistaken for inheritance', () => {
    expect(initialFeedCleanupMode(0)).toBe('count');
    expect(initialFeedCleanupMode(-1)).toBe('count');
  });
});

describe('describeEffectiveCleanupPolicy', () => {
  it('describes inherited global age retention', () => {
    const policy: EffectiveCleanupPolicy = {
      type: 'age',
      source: 'global',
      retention_days: 14,
      inherited: true,
      orphan_maintenance_active: true,
    };

    expect(describeEffectiveCleanupPolicy(policy)).toBe(
      'Inheriting the global policy: processed episode files older than 14 days can be removed.',
    );
  });

  it('describes newest successfully processed episode retention', () => {
    const policy: EffectiveCleanupPolicy = {
      type: 'count',
      source: 'feed',
      retention_count: 4,
      inherited: false,
      orphan_maintenance_active: true,
    };

    expect(describeEffectiveCleanupPolicy(policy)).toBe(
      'Keeping the newest 4 successfully processed episodes for this feed.',
    );
  });

  it('distinguishes inherited global-disabled cleanup from invalid feed cleanup', () => {
    const inheritedDisabled: EffectiveCleanupPolicy = {
      type: 'disabled',
      source: 'global',
      retention_days: null,
      inherited: true,
      orphan_maintenance_active: true,
    };
    const invalidFeed: EffectiveCleanupPolicy = {
      type: 'disabled',
      source: 'feed',
      retention_count: 0,
      inherited: false,
      invalid_configured_value: true,
      orphan_maintenance_active: true,
    };

    expect(describeEffectiveCleanupPolicy(inheritedDisabled)).toContain(
      'global age cleanup is disabled',
    );
    expect(describeEffectiveCleanupPolicy(invalidFeed)).toContain(
      'invalid per-feed count',
    );
    expect(describeEffectiveCleanupPolicy(inheritedDisabled)).not.toBe(
      describeEffectiveCleanupPolicy(invalidFeed),
    );
  });
});

describe('describeGlobalFeedPolicy', () => {
  it('summarizes the current global age policy inherited by null overrides', () => {
    expect(describeGlobalFeedPolicy(21)).toBe(
      'Global policy: remove processed episode files older than 21 days.',
    );
  });

  it('makes inherited global-disabled cleanup explicit', () => {
    expect(describeGlobalFeedPolicy(null)).toBe(
      'Global policy: age-based episode cleanup is disabled; orphan maintenance still runs.',
    );
  });

  it.each([0, -1, 36_501])(
    'treats legacy invalid global retention %s as disabled',
    (retentionDays) => {
      expect(describeGlobalFeedPolicy(retentionDays)).toContain(
        'age-based episode cleanup is disabled',
      );
    },
  );
});

describe('feedCleanupSaveMessage', () => {
  it.each([
    [
      { requested: true, status: 'queued' },
      'Policy saved: keep the newest 3 successfully processed episodes. Cleanup was queued and will run shortly.',
    ],
    [
      { requested: true, status: 'coalesced' },
      'Policy saved: keep the newest 3 successfully processed episodes. Cleanup is already queued or running.',
    ],
    [
      { requested: true, status: 'scheduler_disabled' },
      'Policy saved: keep the newest 3 successfully processed episodes. Automatic cleanup is disabled on this server; enable the scheduler or run maintenance from an external process.',
    ],
  ] satisfies Array<[CleanupDispatch, string]>)('describes a %s count-policy dispatch', (dispatch, expected) => {
    expect(feedCleanupSaveMessage(3, dispatch)).toBe(expected);
  });

  it('confirms inheritance and a queued enforcement pass', () => {
    expect(
      feedCleanupSaveMessage(null, { requested: true, status: 'queued' }),
    ).toBe(
      'Policy saved: inherit the global cleanup policy. Cleanup was queued and will run shortly.',
    );
  });
});
