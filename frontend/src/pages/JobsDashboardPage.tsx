import { useState, type CSSProperties, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { jobsApi } from '../services/api';
import { useTheme } from '../contexts/ThemeContext';
import type {
  JobsDashboard,
  JobsDashboardDaily,
  JobsDashboardFeedRow,
  JobsDashboardRecentJob,
  JobsDashboardUserRow,
} from '../types';

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

const STATUS_COLORS: Record<string, string> = {
  completed: '#8b5cf6',
  failed: '#ef4444',
  skipped: '#a78bfa',
  cancelled: '#6b7280',
  pending: '#ec4899',
  running: '#06b6d4',
};

function MiniBarChart({ data, maxDays }: { data: JobsDashboardDaily[]; maxDays: number }) {
  if (data.length === 0) return <div className="text-sm text-gray-400 py-8 text-center">No data for this period</div>;
  const maxTotal = Math.max(...data.map((d) => d.total), 1);
  const barWidth = Math.max(4, Math.floor(100 / Math.min(data.length, maxDays)));

  return (
    <div className="flex items-end gap-px h-32 w-full overflow-hidden">
      {data.slice(-maxDays).map((day) => {
        const height = Math.max(2, (day.total / maxTotal) * 100);
        const completed = day.completed || 0;
        const failed = day.failed || 0;
        const other = day.total - completed - failed;
        return (
          <div
            key={day.date}
            className="flex flex-col justify-end flex-1 min-w-[4px] group relative"
            style={{ maxWidth: `${barWidth}%` }}
            title={`${day.date}: ${day.total} jobs (${completed} completed, ${failed} failed)`}
          >
            <div className="flex flex-col" style={{ height: `${height}%` }}>
              {other > 0 && (
                <div
                  className="rounded-t-sm"
                  style={{
                    flex: other,
                    backgroundColor: '#a78bfa',
                    minHeight: 1,
                  }}
                />
              )}
              {failed > 0 && (
                <div
                  style={{
                    flex: failed,
                    backgroundColor: '#ef4444',
                    minHeight: 1,
                  }}
                />
              )}
              {completed > 0 && (
                <div
                  className="rounded-b-sm"
                  style={{
                    flex: completed,
                    backgroundColor: '#8b5cf6',
                    minHeight: 1,
                  }}
                />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  icon,
  style,
}: {
  label: string;
  value: string | number;
  sub?: ReactNode;
  icon: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <div
      className="bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 p-4 shadow-sm unicorn-card"
      style={style}
    >
      <div className="flex items-center gap-3">
        <div className="p-2.5 bg-gradient-to-br from-purple-100 to-purple-200 rounded-xl flex-shrink-0">
          {icon}
        </div>
        <div className="min-w-0">
          <p className="text-xs text-purple-500">{label}</p>
          <p className="text-xl font-bold text-purple-900">{value}</p>
          {sub && <p className="text-xs text-gray-500">{sub}</p>}
        </div>
      </div>
    </div>
  );
}

export default function JobsDashboardPage() {
  const { theme } = useTheme();
  const isOriginal = theme === 'original';
  const [days, setDays] = useState(30);
  const failedHistoryHref = '/jobs/history?status=failed';

  const { data: dashboard, isLoading } = useQuery<JobsDashboard>({
    queryKey: ['jobs-dashboard', days],
    queryFn: () => jobsApi.getDashboard(days),
  });

  const cardStyle = isOriginal
    ? { backgroundColor: 'rgba(24, 62, 114, 0.46)', borderColor: 'rgba(147, 197, 253, 0.28)' }
    : undefined;

  const sectionHeaderStyle = isOriginal
    ? {
        background: 'linear-gradient(90deg, rgba(17, 61, 112, 0.92), rgba(34, 96, 162, 0.9), rgba(17, 61, 112, 0.92))',
        borderColor: 'rgba(125, 211, 252, 0.34)',
      }
    : undefined;

  const textPrimary = isOriginal ? 'text-blue-100' : 'text-purple-900';
  const textSecondary = isOriginal ? 'text-blue-200' : 'text-purple-500';

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-500" />
      </div>
    );
  }

  const overview = dashboard?.overview;
  const perf = dashboard?.performance;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className={`text-2xl font-bold ${textPrimary}`}>Jobs</h1>
          <p className={`${textSecondary} mt-1 text-sm`}>Overview, analytics, and recent processing activity</p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/jobs/history"
            className={`px-3 py-1.5 text-sm font-medium rounded-xl border transition-colors ${
              isOriginal
                ? 'border-blue-400/30 text-blue-200 hover:bg-blue-800/30'
                : 'border-purple-200 text-purple-700 hover:bg-purple-50'
            }`}
          >
            History
          </Link>
          <div className="flex rounded-xl border border-purple-200 overflow-hidden">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`px-3 py-1.5 text-sm font-medium transition-colors ${
                  days === d
                    ? 'bg-gradient-to-r from-purple-500 to-pink-500 text-white'
                    : isOriginal
                    ? 'bg-blue-900/30 text-blue-200 hover:bg-blue-800/40'
                    : 'bg-white/80 text-purple-700 hover:bg-purple-50'
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Top Stats Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          label="Total Jobs"
          value={overview?.total_period ?? 0}
          sub={`${overview?.total_all_time ?? 0} all time`}
          style={cardStyle}
          icon={
            <svg className="w-5 h-5 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
          }
        />
        <StatCard
          label="Completed"
          value={overview?.by_status?.completed ?? 0}
          sub={
            <Link
              to={failedHistoryHref}
              className={`inline-flex items-center gap-1 text-xs font-medium transition-colors ${
                isOriginal ? 'text-red-200 hover:text-red-100' : 'text-red-600 hover:text-red-700'
              }`}
            >
              {overview?.by_status?.failed ?? 0} failed
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </Link>
          }
          style={cardStyle}
          icon={
            <svg className="w-5 h-5 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
        />
        <StatCard
          label="Avg Duration"
          value={perf ? formatDuration(perf.avg_duration_seconds) : '—'}
          sub={perf ? `${formatDuration(perf.min_duration_seconds)} – ${formatDuration(perf.max_duration_seconds)}` : undefined}
          style={cardStyle}
          icon={
            <svg className="w-5 h-5 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
        />
        <StatCard
          label="Ads Removed"
          value={perf?.total_ads_removed ?? 0}
          sub={perf ? `${formatDuration(perf.total_time_removed_seconds)} removed · ${perf.avg_percentage_removed}% avg` : undefined}
          style={cardStyle}
          icon={
            <svg className="w-5 h-5 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
            </svg>
          }
        />
      </div>

      {/* Daily Chart + Status Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div
          className="lg:col-span-2 bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 shadow-sm overflow-hidden unicorn-card"
          style={cardStyle}
        >
          <div
            className={isOriginal ? 'px-6 py-4 border-b' : 'px-6 py-4 border-b border-purple-100/50 bg-gradient-to-r from-pink-50/50 via-purple-50/50 to-cyan-50/50'}
            style={sectionHeaderStyle}
          >
            <h2 className={`text-lg font-semibold ${textPrimary}`}>Jobs Over Time</h2>
          </div>
          <div className="p-6">
            <MiniBarChart data={dashboard?.daily ?? []} maxDays={days} />
            <div className="flex items-center gap-4 mt-3 text-xs text-gray-500">
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: '#8b5cf6' }} />
                Completed
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: '#ef4444' }} />
                Failed
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: '#a78bfa' }} />
                Other
              </span>
            </div>
          </div>
        </div>

        <div
          className="bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 shadow-sm overflow-hidden unicorn-card"
          style={cardStyle}
        >
          <div
            className={isOriginal ? 'px-6 py-4 border-b' : 'px-6 py-4 border-b border-purple-100/50 bg-gradient-to-r from-cyan-50/50 via-purple-50/50 to-pink-50/50'}
            style={sectionHeaderStyle}
          >
            <h2 className={`text-lg font-semibold ${textPrimary}`}>By Status</h2>
          </div>
          <div className="p-6 space-y-3">
            {overview?.by_status && Object.entries(overview.by_status)
              .sort(([, a], [, b]) => b - a)
              .map(([status, count]) => {
                const rowContent = (
                  <>
                    <div className="flex items-center gap-2">
                      <span
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: STATUS_COLORS[status] || '#6b7280' }}
                      />
                      <span className="text-sm capitalize text-gray-700">{status}</span>
                    </div>
                    <span className="text-sm font-semibold text-gray-900">{count}</span>
                  </>
                );

                if (status === 'failed') {
                  return (
                    <Link
                      key={status}
                      to={failedHistoryHref}
                      className="flex items-center justify-between rounded-lg px-2 py-1 -mx-2 hover:bg-red-50/60 transition-colors"
                    >
                      {rowContent}
                    </Link>
                  );
                }

                return (
                  <div key={status} className="flex items-center justify-between">
                    {rowContent}
                  </div>
                );
              })}
            {overview?.by_trigger_source && (
              <>
                <div className="border-t border-gray-100 pt-3 mt-3">
                  <p className="text-xs font-medium text-gray-500 mb-2">By Trigger</p>
                  {Object.entries(overview.by_trigger_source)
                    .filter(([, count]) => count > 0)
                    .sort(([, a], [, b]) => b - a)
                    .map(([src, count]) => (
                      <div key={src} className="flex items-center justify-between py-0.5">
                        <span className="text-xs text-gray-600">{src.replace(/_/g, ' ')}</span>
                        <span className="text-xs font-medium text-gray-800">{count}</span>
                      </div>
                    ))}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Per User + Per Podcast */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Jobs Per User */}
        <div
          className="bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 shadow-sm overflow-hidden unicorn-card"
          style={cardStyle}
        >
          <div
            className={isOriginal ? 'px-6 py-4 border-b' : 'px-6 py-4 border-b border-purple-100/50 bg-gradient-to-r from-pink-50/50 via-purple-50/50 to-cyan-50/50'}
            style={sectionHeaderStyle}
          >
            <h2 className={`text-lg font-semibold ${textPrimary}`}>Jobs Per User</h2>
          </div>
          <div className="divide-y divide-gray-100">
            {(dashboard?.by_user ?? []).length === 0 ? (
              <div className="px-6 py-8 text-center text-sm text-gray-400">No user data</div>
            ) : (
              dashboard!.by_user.map((u: JobsDashboardUserRow) => {
                const successRate = u.total > 0 ? Math.round((u.completed / u.total) * 100) : 0;
                return (
                  <div key={u.user_id} className="px-6 py-3 flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-gray-900">{u.username}</p>
                      <p className="text-xs text-gray-500">
                        {u.completed} completed · {u.failed} failed
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-lg font-bold text-purple-700">{u.total}</p>
                      <p className="text-xs text-gray-500">{successRate}% success</p>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Jobs Per Podcast */}
        <div
          className="bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 shadow-sm overflow-hidden unicorn-card"
          style={cardStyle}
        >
          <div
            className={isOriginal ? 'px-6 py-4 border-b' : 'px-6 py-4 border-b border-purple-100/50 bg-gradient-to-r from-cyan-50/50 via-purple-50/50 to-pink-50/50'}
            style={sectionHeaderStyle}
          >
            <h2 className={`text-lg font-semibold ${textPrimary}`}>Jobs Per Podcast</h2>
          </div>
          <div className="divide-y divide-gray-100">
            {(dashboard?.by_feed ?? []).length === 0 ? (
              <div className="px-6 py-8 text-center text-sm text-gray-400">No podcast data</div>
            ) : (
              dashboard!.by_feed.map((f: JobsDashboardFeedRow) => {
                const content = (
                  <>
                    {f.image_url ? (
                      <img src={f.image_url} alt="" className="w-8 h-8 rounded-lg object-cover flex-shrink-0" />
                    ) : (
                      <div className="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0">
                        <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                        </svg>
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">{f.title}</p>
                      <p className="text-xs text-gray-500">{f.completed} completed</p>
                    </div>
                    <span className="text-lg font-bold text-purple-700">{f.total}</span>
                  </>
                );

                if (f.feed_id == null) {
                  return (
                    <div
                      key={`${f.title}-unknown`}
                      className="px-6 py-3 flex items-center gap-3"
                    >
                      {content}
                    </div>
                  );
                }

                return (
                  <Link
                    key={f.feed_id}
                    to={`/podcasts?feed=${f.feed_id}`}
                    className="px-6 py-3 flex items-center gap-3 hover:bg-purple-50/50 transition-colors"
                  >
                    {content}
                  </Link>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Recent Completed Jobs */}
      <div
        className="bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 shadow-sm overflow-hidden unicorn-card"
        style={cardStyle}
      >
        <div
          className={isOriginal ? 'px-6 py-4 border-b' : 'px-6 py-4 border-b border-purple-100/50 bg-gradient-to-r from-pink-50/50 via-purple-50/50 to-cyan-50/50'}
          style={sectionHeaderStyle}
        >
          <h2 className={`text-lg font-semibold ${textPrimary}`}>Recent Completed Jobs</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 uppercase">Episode</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 uppercase">Completed</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-gray-500 uppercase">Duration</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-gray-500 uppercase">Ads</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-gray-500 uppercase">Time Saved</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 uppercase">By</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {(dashboard?.recent_completed ?? []).length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-400">
                    No completed jobs in this period
                  </td>
                </tr>
              ) : (
                dashboard!.recent_completed.map((job: JobsDashboardRecentJob) => (
                  <tr key={job.job_id} className="hover:bg-purple-50/30">
                    <td className="px-4 py-2.5">
                      <p className="font-medium text-gray-900 truncate max-w-[200px]">{job.post_title || 'Untitled'}</p>
                      <p className="text-xs text-gray-500 truncate max-w-[200px]">{job.feed_title}</p>
                    </td>
                    <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap">{formatDate(job.completed_at)}</td>
                    <td className="px-4 py-2.5 text-right text-gray-600 whitespace-nowrap">
                      {job.duration_seconds != null ? formatDuration(job.duration_seconds) : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-600 whitespace-nowrap">
                      {job.ads_removed ?? '—'}
                      {job.percentage_removed != null && (
                        <span className="text-xs text-gray-400 ml-1">({job.percentage_removed}%)</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-600 whitespace-nowrap">
                      {job.time_removed_seconds != null ? formatDuration(job.time_removed_seconds) : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap">{job.triggered_by || '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
