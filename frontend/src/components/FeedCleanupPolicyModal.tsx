import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'react-hot-toast';

import { useTheme } from '../contexts/ThemeContext';
import {
  FEED_RETENTION_COUNT_MAX,
  describeEffectiveCleanupPolicy,
  describeGlobalFeedPolicy,
  feedCleanupSaveMessage,
  initialFeedCleanupMode,
  toFeedRetentionCount,
  type FeedCleanupMode,
} from '../feedCleanupPolicy';
import { useEscapeKey } from '../hooks/useEscapeKey';
import { configApi, feedsApi } from '../services/api';
import { isDarkSurfaceTheme } from '../theme';
import type { Feed } from '../types';

interface FeedCleanupPolicyModalProps {
  feed: Feed;
  onClose: () => void;
}

function requestErrorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = (error as {
      response?: { data?: { error?: string; message?: string } };
    }).response;
    return (
      response?.data?.error ||
      response?.data?.message ||
      'Failed to save the storage cleanup policy.'
    );
  }
  return error instanceof Error
    ? error.message
    : 'Failed to save the storage cleanup policy.';
}

export default function FeedCleanupPolicyModal({
  feed,
  onClose,
}: FeedCleanupPolicyModalProps) {
  const { theme } = useTheme();
  const isOriginal = theme === 'original';
  const isDark = isDarkSurfaceTheme(theme);
  const queryClient = useQueryClient();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const [mode, setMode] = useState<FeedCleanupMode>(() =>
    initialFeedCleanupMode(feed.processed_episode_retention_count),
  );
  const [countInput, setCountInput] = useState(() =>
    String(feed.processed_episode_retention_count ?? 5),
  );

  const { data: configResponse, isLoading: globalPolicyLoading } = useQuery({
    queryKey: ['config'],
    queryFn: configApi.getConfig,
  });

  const countError = useMemo(() => {
    if (mode !== 'count') {
      return null;
    }
    try {
      toFeedRetentionCount(mode, countInput);
      return null;
    } catch (error) {
      return error instanceof Error
        ? error.message
        : `Enter a whole number between 1 and ${FEED_RETENTION_COUNT_MAX}.`;
    }
  }, [countInput, mode]);

  const saveMutation = useMutation({
    mutationFn: (retentionCount: number | null) =>
      feedsApi.setCleanupPolicy(feed.id, retentionCount),
    onSuccess: async (response, retentionCount) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['feeds'] }),
        queryClient.invalidateQueries({ queryKey: ['episodes', feed.id] }),
      ]);
      const message = feedCleanupSaveMessage(
        retentionCount,
        response.cleanup_dispatch,
      );
      if (response.cleanup_dispatch.status === 'scheduler_disabled') {
        toast.error(message);
      } else {
        toast.success(message);
      }
      onClose();
    },
    onError: (error) => {
      toast.error(requestErrorMessage(error));
    },
  });

  const closeIfIdle = useCallback(() => {
    if (!saveMutation.isPending) {
      onClose();
    }
  }, [onClose, saveMutation.isPending]);

  useEscapeKey(true, closeIfIdle);

  useEffect(() => {
    const previousFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const dialog = dialogRef.current;
    closeButtonRef.current?.focus();

    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== 'Tab' || !dialog) {
        return;
      }
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hasAttribute('hidden'));
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    dialog?.addEventListener('keydown', trapFocus);
    return () => {
      dialog?.removeEventListener('keydown', trapFocus);
      previousFocus?.focus();
    };
  }, []);

  const submitPolicy = () => {
    if (countError || saveMutation.isPending) {
      return;
    }
    try {
      saveMutation.mutate(toFeedRetentionCount(mode, countInput));
    } catch (error) {
      toast.error(requestErrorMessage(error));
    }
  };

  const globalRetentionDays =
    configResponse?.config.app.post_cleanup_retention_days;
  const globalPolicySummary = globalPolicyLoading
    ? 'Loading the current global policy…'
    : configResponse
      ? describeGlobalFeedPolicy(globalRetentionDays)
      : 'The current global policy could not be loaded. The server will apply its saved policy.';

  const panelStyle = isOriginal
    ? {
        backgroundColor: '#0b234d',
        borderColor: 'rgba(96, 165, 250, 0.45)',
      }
    : undefined;

  return createPortal(
    <div
      className="fixed inset-0 flex items-center justify-center p-4"
      style={{
        zIndex: 9999,
        backgroundColor: isOriginal
          ? 'rgba(2, 8, 23, 0.82)'
          : 'rgba(88, 28, 135, 0.62)',
        backdropFilter: isOriginal ? 'none' : 'blur(3px)',
      }}
      onClick={closeIfIdle}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="feed-cleanup-title"
        tabIndex={-1}
        className="modal-content flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-purple-200 bg-white shadow-2xl dark:border-purple-700 dark:bg-slate-900"
        style={panelStyle}
        onClick={(event) => event.stopPropagation()}
      >
        <div
          className="flex items-start justify-between gap-4 border-b border-purple-100 bg-gradient-to-r from-pink-50 via-purple-50 to-cyan-50 p-6 dark:border-purple-800 dark:from-purple-950/60 dark:via-slate-900 dark:to-cyan-950/40"
          style={
            isOriginal
              ? {
                  borderColor: 'rgba(96, 165, 250, 0.32)',
                  background: 'linear-gradient(to right, #123867, #1b4f87, #123867)',
                }
              : undefined
          }
        >
          <div className="min-w-0">
            <h2
              id="feed-cleanup-title"
              className={`text-xl font-bold ${
                isOriginal ? 'text-blue-100' : 'text-purple-900 dark:text-purple-100'
              }`}
            >
              Storage cleanup
            </h2>
            <p
              className={`mt-1 truncate text-sm ${
                isOriginal ? 'text-blue-200' : 'text-purple-600 dark:text-purple-300'
              }`}
            >
              {feed.title}
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            aria-label="Close storage cleanup settings"
            disabled={saveMutation.isPending}
            onClick={closeIfIdle}
            className={`rounded-lg p-2 transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              isOriginal
                ? 'text-blue-200 hover:bg-blue-800/45 hover:text-blue-50'
                : 'text-purple-400 hover:bg-purple-100 hover:text-purple-600 dark:hover:bg-purple-900/40'
            }`}
          >
            <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="overflow-y-auto p-6">
          <div
            className={`rounded-xl border p-4 ${
              isOriginal
                ? 'border-blue-300/30 bg-blue-950/35 text-blue-100'
                : 'border-purple-200 bg-purple-50/70 text-purple-900 dark:border-purple-700 dark:bg-purple-950/35 dark:text-purple-100'
            }`}
          >
            <p className="text-xs font-semibold uppercase tracking-wide opacity-70">
              Current effective policy
            </p>
            <p className="mt-1 text-sm leading-5">
              {describeEffectiveCleanupPolicy(feed.effective_cleanup_policy)}
            </p>
          </div>

          <fieldset className="mt-5 space-y-3">
            <legend
              className={`text-sm font-semibold ${
                isOriginal ? 'text-blue-100' : 'text-gray-900 dark:text-purple-100'
              }`}
            >
              Policy for this feed
            </legend>

            <label
              className={`block cursor-pointer rounded-xl border p-4 transition-colors ${
                mode === 'inherit'
                  ? isOriginal
                    ? 'border-blue-300/70 bg-blue-800/50'
                    : 'border-purple-500 bg-purple-50 dark:bg-purple-900/45'
                  : isOriginal
                    ? 'border-blue-300/25 bg-blue-950/25'
                    : 'border-gray-200 bg-white dark:border-purple-800 dark:bg-slate-900'
              }`}
            >
              <span className="flex items-start gap-3">
                <input
                  type="radio"
                  name="feed-cleanup-mode"
                  value="inherit"
                  checked={mode === 'inherit'}
                  onChange={() => setMode('inherit')}
                  className="mt-1 h-4 w-4"
                />
                <span>
                  <span
                    className={`block text-sm font-semibold ${
                      isOriginal ? 'text-blue-100' : 'text-gray-900 dark:text-purple-100'
                    }`}
                  >
                    Inherit global policy
                  </span>
                  <span
                    className={`mt-1 block text-xs leading-5 ${
                      isOriginal ? 'text-blue-200/80' : 'text-gray-600 dark:text-purple-300'
                    }`}
                  >
                    {globalPolicySummary}
                  </span>
                </span>
              </span>
            </label>

            <label
              className={`block cursor-pointer rounded-xl border p-4 transition-colors ${
                mode === 'count'
                  ? isOriginal
                    ? 'border-blue-300/70 bg-blue-800/50'
                    : 'border-purple-500 bg-purple-50 dark:bg-purple-900/45'
                  : isOriginal
                    ? 'border-blue-300/25 bg-blue-950/25'
                    : 'border-gray-200 bg-white dark:border-purple-800 dark:bg-slate-900'
              }`}
            >
              <span className="flex items-start gap-3">
                <input
                  type="radio"
                  name="feed-cleanup-mode"
                  value="count"
                  checked={mode === 'count'}
                  onChange={() => setMode('count')}
                  className="mt-1 h-4 w-4"
                />
                <span className="min-w-0 flex-1">
                  <span
                    className={`block text-sm font-semibold ${
                      isOriginal ? 'text-blue-100' : 'text-gray-900 dark:text-purple-100'
                    }`}
                  >
                    Keep newest processed episodes
                  </span>
                  <span
                    className={`mt-1 block text-xs leading-5 ${
                      isOriginal ? 'text-blue-200/80' : 'text-gray-600 dark:text-purple-300'
                    }`}
                  >
                    Keep the newest successfully processed episodes using release date ordering.
                  </span>
                  {mode === 'count' && (
                    <span className="mt-3 block max-w-xs">
                      <span
                        id="feed-cleanup-count-label"
                        className={`mb-1 block text-xs font-medium ${
                          isOriginal ? 'text-blue-100' : 'text-gray-700 dark:text-purple-200'
                        }`}
                      >
                        Number of processed episodes to keep
                      </span>
                      <input
                        aria-labelledby="feed-cleanup-count-label"
                        type="number"
                        min={1}
                        max={FEED_RETENTION_COUNT_MAX}
                        step={1}
                        inputMode="numeric"
                        value={countInput}
                        aria-invalid={countError ? 'true' : undefined}
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) => setCountInput(event.target.value)}
                        className={`input w-full ${
                          isDark && !isOriginal ? 'bg-slate-950 text-purple-100' : ''
                        }`}
                      />
                      {countError && (
                        <span className="mt-1 block text-xs text-red-600 dark:text-red-300">
                          {countError}
                        </span>
                      )}
                    </span>
                  )}
                </span>
              </span>
            </label>
          </fieldset>

          <p
            className={`mt-5 text-xs leading-5 ${
              isOriginal ? 'text-blue-200/75' : 'text-gray-600 dark:text-purple-300'
            }`}
          >
            When a limit is exceeded, Podly removes local input and processed audio plus
            processing-derived data. Feed and episode metadata, source URLs, subscriptions,
            and whitelist state are preserved so an episode can be processed again. Equal or
            missing release dates use a deterministic episode order.
          </p>
        </div>

        <div
          className="flex justify-end gap-3 border-t border-purple-100 bg-gray-50 p-5 dark:border-purple-800 dark:bg-slate-950/60"
          style={
            isOriginal
              ? {
                  borderColor: 'rgba(96, 165, 250, 0.3)',
                  backgroundColor: '#081b3d',
                }
              : undefined
          }
        >
          <button
            type="button"
            disabled={saveMutation.isPending}
            onClick={closeIfIdle}
            className={`rounded-xl border px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              isOriginal
                ? 'border-blue-300/45 bg-blue-900/50 text-blue-100 hover:bg-blue-800/60'
                : 'border-purple-200 bg-white text-purple-700 hover:bg-purple-50 dark:border-purple-700 dark:bg-slate-900 dark:text-purple-200'
            }`}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={saveMutation.isPending || Boolean(countError)}
            onClick={submitPolicy}
            className={`rounded-xl px-4 py-2 text-sm font-medium text-white transition-all disabled:cursor-not-allowed disabled:opacity-50 ${
              isOriginal
                ? 'border border-blue-300/55 bg-blue-500 hover:bg-blue-400'
                : 'bg-gradient-to-r from-pink-500 via-purple-500 to-cyan-500 hover:shadow-lg hover:shadow-purple-500/30'
            }`}
          >
            {saveMutation.isPending ? 'Saving policy…' : 'Save policy'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
