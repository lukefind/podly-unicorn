import { useQuery } from '@tanstack/react-query';
import { createPortal } from 'react-dom';
import { authApi } from '../services/api';
import type { UserStats } from '../services/api';
import { useState } from 'react';

interface AdminUserStatsProps {
  onRoleChange?: (username: string, newRole: string) => Promise<void>;
  onDeleteUser?: (username: string) => Promise<void>;
  onResetPassword?: (username: string, password: string) => Promise<void>;
  adminCount?: number;
  currentUsername?: string;
}

export default function AdminUserStats({ onRoleChange, onDeleteUser, onResetPassword, adminCount = 1, currentUsername }: AdminUserStatsProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['admin-user-stats'],
    queryFn: authApi.getUserStats,
    refetchInterval: 30000, // Refresh every 30 seconds
  });

  if (isLoading) {
    return (
      <div className="bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 p-6 shadow-sm">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-purple-100 rounded w-1/3"></div>
          <div className="h-20 bg-purple-50 rounded"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white/80 backdrop-blur-sm rounded-xl border border-red-200/50 p-6 shadow-sm">
        <p className="text-red-600">Failed to load user statistics</p>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-purple-900">User Statistics 👥</h2>
        <div className="text-sm text-purple-500">
          {data.global_stats.total_feeds} feeds • {data.global_stats.total_processed}/{data.global_stats.total_episodes} processed
        </div>
      </div>

      {/* User Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {data.users.map((user) => (
          <UserStatCard 
            key={user.id} 
            user={user}
            onRoleChange={onRoleChange}
            onDeleteUser={onDeleteUser}
            onResetPassword={onResetPassword}
            adminCount={adminCount}
            isCurrentUser={user.username === currentUsername}
          />
        ))}
      </div>
    </div>
  );
}

interface UserStatCardProps {
  user: UserStats;
  onRoleChange?: (username: string, newRole: string) => Promise<void>;
  onDeleteUser?: (username: string) => Promise<void>;
  onResetPassword?: (username: string, password: string) => Promise<void>;
  adminCount: number;
  isCurrentUser?: boolean;
}

interface DownloadAttemptsModalProps {
  userId: number;
  username: string;
  onClose: () => void;
}

function DownloadAttemptsModal({ userId, username, onClose }: DownloadAttemptsModalProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['download-attempts', userId],
    queryFn: () => authApi.getDownloadAttempts({ user_id: userId, limit: 500 }),
  });

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'Unknown';
    const date = new Date(dateStr);
    return date.toLocaleString();
  };

  const getDecisionBadge = (decision: string | null) => {
    switch (decision) {
      case 'SERVED_AUDIO':
        return <span className="px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700">Served</span>;
      case 'TRIGGERED':
        return <span className="px-2 py-0.5 rounded-full text-xs bg-blue-100 text-blue-700">Triggered</span>;
      case 'NOT_READY_NO_TRIGGER':
        return <span className="px-2 py-0.5 rounded-full text-xs bg-yellow-100 text-yellow-700">Not Ready</span>;
      case 'JOB_EXISTS':
        return <span className="px-2 py-0.5 rounded-full text-xs bg-purple-100 text-purple-700">Job Exists</span>;
      case 'COOLDOWN_ACTIVE':
        return <span className="px-2 py-0.5 rounded-full text-xs bg-orange-100 text-orange-700">Cooldown</span>;
      default:
        return <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600">{decision || 'Legacy'}</span>;
    }
  };

  const getAuthTypeBadge = (authType: string | null) => {
    switch (authType) {
      case 'combined':
        return <span className="px-2 py-0.5 rounded-full text-xs bg-pink-100 text-pink-700">Combined</span>;
      case 'feed_scoped':
        return <span className="px-2 py-0.5 rounded-full text-xs bg-cyan-100 text-cyan-700">Feed-Scoped</span>;
      case 'session':
        return <span className="px-2 py-0.5 rounded-full text-xs bg-indigo-100 text-indigo-700">Session</span>;
      default:
        return <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600">{authType || 'Unknown'}</span>;
    }
  };

  const downloadCSV = () => {
    if (!data?.attempts) return;
    
    const headers = ['Date', 'Episode', 'Feed', 'Auth Type', 'Decision', 'Source', 'Processed'];
    const rows = data.attempts.map(a => [
      a.downloaded_at || '',
      a.post_title,
      a.feed_title,
      a.auth_type || '',
      a.decision || '',
      a.download_source,
      a.is_processed ? 'Yes' : 'No',
    ]);
    
    const csvContent = [headers, ...rows]
      .map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
      .join('\n');
    
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `download-attempts-${username}-${new Date().toISOString().split('T')[0]}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return createPortal(
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onClose}
    >
      <div 
        className="rounded-xl shadow-2xl max-w-4xl w-full max-h-[80vh] flex flex-col"
        style={{ backgroundColor: '#1e1b4b' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-purple-700">
          <div>
            <h2 className="text-lg font-bold text-purple-200">Download Attempts</h2>
            <p className="text-sm text-purple-400">User: {username} ({data?.total_count ?? 0} records)</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="px-3 py-1.5 text-sm bg-purple-600 text-white rounded hover:bg-purple-700"
              onClick={downloadCSV}
              disabled={!data?.attempts?.length}
            >
              Download CSV
            </button>
            <button
              type="button"
              className="p-2 text-purple-300 hover:text-purple-100"
              onClick={onClose}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-4">
          {isLoading && (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-600"></div>
            </div>
          )}

          {error && (
            <div className="text-red-400 text-center py-8">Failed to load download attempts</div>
          )}

          {data && data.attempts.length === 0 && (
            <div className="text-purple-400 text-center py-8">No download attempts found</div>
          )}

          {data && data.attempts.length > 0 && (
            <table className="w-full text-sm">
              <thead className="sticky top-0" style={{ backgroundColor: '#2e1065' }}>
                <tr>
                  <th className="text-left p-2 text-purple-300">Date</th>
                  <th className="text-left p-2 text-purple-300">Episode</th>
                  <th className="text-left p-2 text-purple-300">Feed</th>
                  <th className="text-left p-2 text-purple-300">Auth</th>
                  <th className="text-left p-2 text-purple-300">Decision</th>
                  <th className="text-left p-2 text-purple-300">Source</th>
                </tr>
              </thead>
              <tbody>
                {data.attempts.map((attempt) => (
                  <tr key={attempt.id} className="border-b border-purple-800 hover:bg-purple-900/50">
                    <td className="p-2 text-purple-300 whitespace-nowrap">{formatDate(attempt.downloaded_at)}</td>
                    <td className="p-2 text-purple-200 max-w-xs truncate" title={attempt.post_title}>{attempt.post_title}</td>
                    <td className="p-2 text-purple-300 max-w-xs truncate" title={attempt.feed_title}>{attempt.feed_title}</td>
                    <td className="p-2">{getAuthTypeBadge(attempt.auth_type)}</td>
                    <td className="p-2">{getDecisionBadge(attempt.decision)}</td>
                    <td className="p-2 text-purple-400">{attempt.download_source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}

function UserStatCard({ user, onRoleChange, onDeleteUser, onResetPassword, adminCount, isCurrentUser }: UserStatCardProps) {
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showDownloadAttempts, setShowDownloadAttempts] = useState(false);
  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'Never';
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  return (
    <div className="bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 p-5 shadow-sm unicorn-card">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-pink-400 via-purple-400 to-cyan-400 flex items-center justify-center text-white font-bold text-lg">
            {user.username.charAt(0).toUpperCase()}
          </div>
          <div>
            <h3 className="font-semibold text-purple-900">{user.username}</h3>
            <span className={`text-xs px-2 py-0.5 rounded-full ${
              user.role === 'admin' 
                ? 'bg-purple-100 text-purple-700' 
                : 'bg-gray-100 text-gray-600'
            }`}>
              {user.role}
            </span>
          </div>
        </div>
        <div className="text-right text-xs text-purple-400">
          Last active: {formatDate(user.last_activity)}
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-4 gap-2 mb-4">
        <div className="bg-gradient-to-br from-pink-50 to-pink-100 rounded-lg p-2 text-center">
          <div className="text-xl font-bold text-pink-600">{user.episodes_processed}</div>
          <div className="text-xs text-pink-500">Processed</div>
        </div>
        <div className="bg-gradient-to-br from-purple-50 to-purple-100 rounded-lg p-2 text-center">
          <div className="text-xl font-bold text-purple-600">{user.processed_downloads}</div>
          <div className="text-xs text-purple-500">Downloads</div>
          <div className="text-[10px] text-purple-400">RSS: {user.rss_processed_downloads ?? 0}</div>
        </div>
        <div className="bg-gradient-to-br from-cyan-50 to-cyan-100 rounded-lg p-2 text-center">
          <div className="text-sm font-bold text-cyan-600">{user.ad_time_removed_formatted || '0s'}</div>
          <div className="text-xs text-cyan-500">Ads Removed</div>
        </div>
        <div className="bg-gradient-to-br from-indigo-50 to-indigo-100 rounded-lg p-2 text-center">
          <div className="text-xl font-bold text-indigo-600">{user.subscriptions_count ?? 0}</div>
          <div className="text-xs text-indigo-500">Subscribed</div>
        </div>
      </div>

      {/* Recent Downloads */}
      {user.recent_downloads.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs font-medium text-purple-500 dark:text-purple-300">Recent Downloads</div>
            <button
              type="button"
              className="text-xs text-cyan-500 hover:text-cyan-400 underline font-medium"
              onClick={() => setShowDownloadAttempts(true)}
            >
              View all attempts
            </button>
          </div>
          <div className="space-y-1 max-h-24 overflow-y-auto">
            {user.recent_downloads.slice(0, 3).map((download, idx) => (
              <div key={idx} className="flex items-center justify-between text-xs bg-purple-50/50 rounded px-2 py-1">
                <span className="truncate flex-1 text-purple-700">{download.post_title}</span>
                <span className="text-purple-400 ml-2 whitespace-nowrap">
                  {formatDate(download.downloaded_at)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {user.recent_downloads.length === 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs text-purple-300">No downloads yet</div>
            <button
              type="button"
              className="text-xs text-cyan-500 hover:text-cyan-400 underline font-medium"
              onClick={() => setShowDownloadAttempts(true)}
            >
              View all attempts
            </button>
          </div>
        </div>
      )}

      {/* Download Attempts Modal */}
      {showDownloadAttempts && (
        <DownloadAttemptsModal
          userId={user.id}
          username={user.username}
          onClose={() => setShowDownloadAttempts(false)}
        />
      )}

      {/* User Controls */}
      {(onRoleChange || onDeleteUser || onResetPassword) && (
        <div className="border-t border-purple-200/50 pt-3 mt-3">
          <div className="flex flex-wrap items-center gap-2">
            {onRoleChange && (
              <select
                className="text-xs px-2 py-1 rounded border border-purple-200 bg-white dark:bg-slate-800 dark:border-purple-600 dark:text-purple-200"
                value={user.role}
                onChange={(e) => {
                  if (e.target.value !== user.role) {
                    void onRoleChange(user.username, e.target.value);
                  }
                }}
                disabled={(user.role === 'admin' && adminCount <= 1) || isCurrentUser}
                title={isCurrentUser ? "You cannot change your own role" : undefined}
              >
                <option value="user">user</option>
                <option value="admin">admin</option>
              </select>
            )}
            {onResetPassword && (
              <button
                type="button"
                className="text-xs px-2 py-1 border border-purple-200 dark:border-purple-600 rounded hover:bg-purple-50 dark:hover:bg-purple-800 dark:text-purple-200"
                onClick={() => setShowPasswordForm(!showPasswordForm)}
              >
                {showPasswordForm ? 'Cancel' : 'Set password'}
              </button>
            )}
            {onDeleteUser && (
              <button
                type="button"
                className="text-xs px-2 py-1 border border-red-200 text-red-600 rounded hover:bg-red-50 disabled:opacity-50"
                onClick={() => void onDeleteUser(user.username)}
                disabled={user.role === 'admin' && adminCount <= 1}
              >
                Delete
              </button>
            )}
          </div>

          {showPasswordForm && onResetPassword && (
            <form 
              className="mt-2 flex flex-wrap gap-2 items-end"
              onSubmit={(e) => {
                e.preventDefault();
                if (newPassword && newPassword === confirmPassword) {
                  void onResetPassword(user.username, newPassword);
                  setNewPassword('');
                  setConfirmPassword('');
                  setShowPasswordForm(false);
                }
              }}
            >
              <input
                type="password"
                placeholder="New password"
                className="text-xs px-2 py-1 rounded border border-purple-200 dark:bg-slate-800 dark:border-purple-600 w-24"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
              />
              <input
                type="password"
                placeholder="Confirm"
                className="text-xs px-2 py-1 rounded border border-purple-200 dark:bg-slate-800 dark:border-purple-600 w-24"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
              <button
                type="submit"
                className="text-xs px-2 py-1 rounded bg-purple-600 text-white hover:bg-purple-700"
              >
                Update
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
