import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';

interface NavItem {
  path: string;
  label: string;
  icon: React.ReactNode;
  adminOnly?: boolean;
}

const navItems: NavItem[] = [
  {
    path: '/',
    label: 'Dashboard',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
      </svg>
    ),
  },
  {
    path: '/podcasts',
    label: 'Podcasts',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
      </svg>
    ),
  },
  {
    path: '/jobs',
    label: 'Jobs',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
      </svg>
    ),
  },
  {
    path: '/presets',
    label: 'Presets',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
      </svg>
    ),
  },
  {
    path: '/settings',
    label: 'Settings',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
    adminOnly: true,
  },
];

interface SidebarProps {
  collapsed?: boolean;
  onToggle?: () => void;
}

export default function Sidebar({ collapsed = false, onToggle }: SidebarProps) {
  const location = useLocation();
  const { requireAuth, user, logout } = useAuth();

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  const filteredNavItems = navItems.filter(item => {
    if (item.adminOnly) {
      return !requireAuth || user?.role === 'admin';
    }
    return true;
  });

  return (
    <aside className={`bg-gradient-to-b from-purple-900 via-purple-950 to-slate-900 text-white flex flex-col transition-all duration-300 ${collapsed ? 'w-16' : 'w-64'} shadow-xl`}>
      {/* Logo */}
      <div className="h-16 flex items-center px-4 border-b border-purple-800/50">
        <Link to="/" className="flex items-center gap-3">
          <img 
            src="/images/logos/unicorn-logo.png" 
            alt="Podly Unicorn" 
            className="h-10 w-10 object-contain"
          />
          {!collapsed && (
            <span className="text-lg font-bold rainbow-text">
              Podly Unicorn
            </span>
          )}
        </Link>
        {onToggle && (
          <button
            onClick={onToggle}
            className="ml-auto p-2 rounded-lg bg-purple-700/50 hover:bg-purple-600/70 transition-colors border border-purple-500/30"
          >
            <svg className={`w-5 h-5 transition-transform text-white ${collapsed ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
            </svg>
          </button>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 px-2 space-y-1">
        {filteredNavItems.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all ${
              isActive(item.path)
                ? 'bg-gradient-to-r from-pink-500/80 via-purple-500/80 to-cyan-500/80 text-white shadow-lg shadow-purple-500/30'
                : 'text-purple-200 hover:text-white hover:bg-purple-800/40'
            }`}
            title={collapsed ? item.label : undefined}
          >
            {item.icon}
            {!collapsed && <span className="font-medium">{item.label}</span>}
          </Link>
        ))}
      </nav>

      {/* User section */}
      {requireAuth && user && (
        <div className="p-4 border-t border-purple-800/50">
          <div className={`flex items-center ${collapsed ? 'justify-center' : 'gap-3'}`}>
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-pink-400 via-purple-400 to-cyan-400 flex items-center justify-center text-sm font-bold shadow-lg">
              {user.username.charAt(0).toUpperCase()}
            </div>
            {!collapsed && (
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{user.username}</p>
                <p className="text-xs text-purple-300 capitalize">{user.role}</p>
              </div>
            )}
            {!collapsed && (
              <button
                onClick={logout}
                className="p-1.5 rounded-lg hover:bg-purple-800/50 text-purple-300 hover:text-white transition-colors"
                title="Logout"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
              </button>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
