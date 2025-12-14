import { useQuery } from '@tanstack/react-query';
import { authApi } from '../services/api';
import type { UserStats } from '../services/api';
import { useState } from 'react';

interface AdminUserStatsProps {
  onRoleChange?: (username: string, newRole: string) => Promise<void>;
  onDeleteUser?: (username: string) => Promise<void>;
  onResetPassword?: (username: string, password: string) => Promise<void>;
  adminCount?: number;
}

export default function AdminUserStats({ onRoleChange, onDeleteUser, onResetPassword, adminCount = 1 }: AdminUserStatsProps) {
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
}

function UserStatCard({ user, onRoleChange, onDeleteUser, onResetPassword, adminCount }: UserStatCardProps) {
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
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
          <div className="text-xs font-medium text-purple-500 mb-2">Recent Downloads</div>
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
        <div className="text-xs text-purple-300 text-center py-2">
          No downloads yet
        </div>
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
                disabled={user.role === 'admin' && adminCount <= 1}
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
