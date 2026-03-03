import { useState, type CSSProperties } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import { BrowserRouter as Router, Routes, Route, Navigate, Link } from 'react-router-dom';
import { AudioPlayerProvider } from './contexts/AudioPlayerContext';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { ThemeProvider, useTheme } from './contexts/ThemeContext';
import Sidebar from './components/layout/Sidebar';
import OnboardingModal, { useOnboarding } from './components/OnboardingModal';
import DashboardPage from './pages/DashboardPage';
import PodcastsLayout from './layouts/PodcastsLayout';
import FeedDetailView from './pages/FeedDetailView';
import CombinedEpisodesView from './pages/CombinedEpisodesView';
import JobsPage from './pages/JobsPage';
import PresetsPage from './pages/PresetsPage';
import ConfigPage from './pages/ConfigPage';
import LoginPage from './pages/LoginPage';
import SignupPage from './pages/SignupPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import ResetPasswordPage from './pages/ResetPasswordPage';
import SubscriptionsPage from './pages/SubscriptionsPage';
import TriggerPage from './pages/TriggerPage';
import AudioPlayer from './components/AudioPlayer';
import { getThemeBrandClass, getThemeBrandName, getThemeLogoPath } from './theme';
import './App.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 0,
      gcTime: 0,
      refetchOnMount: 'always',
      refetchOnWindowFocus: 'always',
      refetchOnReconnect: 'always',
    },
  },
});

function AppShell() {
  const { status, requireAuth, isAuthenticated, user } = useAuth();
  const { theme } = useTheme();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { showOnboarding, completeOnboarding } = useOnboarding();
  const logoPath = getThemeLogoPath(theme);
  const brandName = getThemeBrandName(theme);
  const brandClass = getThemeBrandClass(theme);
  const mobileHeaderOffset = 'calc(3.5rem + env(safe-area-inset-top, 0px))';
  const appShellStyle: CSSProperties = {
    ['--mobile-header-offset' as string]: mobileHeaderOffset,
  };

  const mobileHeaderClasses = theme === 'original'
    ? 'bg-gradient-to-r from-blue-700 via-blue-800 to-blue-900'
    : 'bg-gradient-to-r from-purple-800 via-purple-900 to-slate-900';

  if (status === 'loading') {
    return (
      <div className="h-screen flex items-center justify-center bg-gray-900">
        <div className="flex flex-col items-center gap-4">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500" />
          <p className="text-sm text-gray-400">Loading...</p>
        </div>
      </div>
    );
  }

  if (requireAuth && !isAuthenticated) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  const showSettingsRoute = !requireAuth || user?.role === 'admin';

  return (
    <div className="h-screen h-[100dvh] flex overflow-hidden bg-gray-100" style={appShellStyle}>
      {/* Mobile Header */}
      <div
        className={`lg:hidden fixed top-0 left-0 right-0 z-40 flex items-center px-4 shadow-lg ${mobileHeaderClasses}`}
        style={{ height: 'var(--mobile-header-offset)', paddingTop: 'env(safe-area-inset-top, 0px)' }}
      >
        <button
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className={`p-2 rounded-lg text-white ${theme === 'original' ? 'hover:bg-blue-700/50' : 'hover:bg-purple-700/50'}`}
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {mobileMenuOpen ? (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            )}
          </svg>
        </button>
        <Link to="/" className="ml-3 flex items-center gap-2 min-w-0">
          <img src={logoPath} alt={brandName} className="w-7 h-7 object-contain flex-shrink-0" />
          <span className={`text-lg font-bold truncate ${brandClass}`}>{brandName}</span>
        </Link>
      </div>

      {/* Mobile Sidebar Overlay */}
      {mobileMenuOpen && (
        <div 
          className="lg:hidden fixed inset-0 z-30 bg-black/50"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* Sidebar - hidden on mobile unless menu open */}
      <div className={`
        mobile-sidebar-offset
        fixed lg:relative z-40 lg:z-auto
        transform lg:transform-none transition-transform duration-300
        ${mobileMenuOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        bottom-0 lg:bottom-auto lg:h-full
      `}>
        <Sidebar 
          collapsed={sidebarCollapsed} 
          onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
          onNavigate={() => setMobileMenuOpen(false)}
          isMobile={mobileMenuOpen}
        />
      </div>

      {/* Main Content */}
      <div className="mobile-main-offset flex-1 flex flex-col overflow-hidden lg:pt-0">
        <main className="flex-1 overflow-y-auto overflow-x-hidden overscroll-contain p-3 sm:p-4 lg:p-6 pb-24 lg:pb-6">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/podcasts" element={<PodcastsLayout />}>
              <Route index element={<FeedDetailView />} />
              <Route path="combined" element={<CombinedEpisodesView />} />
            </Route>
            <Route path="/jobs" element={<JobsPage />} />
            {showSettingsRoute && <Route path="/subscriptions" element={<SubscriptionsPage />} />}
            {showSettingsRoute && <Route path="/presets" element={<PresetsPage />} />}
            {showSettingsRoute && <Route path="/settings" element={<ConfigPage />} />}
            {!requireAuth && <Route path="/login" element={<LoginPage />} />}
            {!requireAuth && <Route path="/signup" element={<SignupPage />} />}
            {!requireAuth && <Route path="/forgot-password" element={<ForgotPasswordPage />} />}
            {!requireAuth && <Route path="/reset-password" element={<ResetPasswordPage />} />}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>

        <AudioPlayer />
      </div>

      {/* Onboarding Modal for first-time users */}
      {showOnboarding && isAuthenticated && (
        <OnboardingModal onClose={completeOnboarding} />
      )}

      <Toaster 
        position="top-center" 
        toastOptions={{ 
          duration: 3000,
          style: {
            background: theme === 'original'
              ? 'linear-gradient(135deg, #dbeafe 0%, #bfdbfe 50%, #cffafe 100%)'
              : 'linear-gradient(135deg, #fdf2f8 0%, #f3e8ff 50%, #ecfeff 100%)',
            color: theme === 'original' ? '#1e3a8a' : '#581c87',
            border: theme === 'original'
              ? '1px solid rgba(96, 165, 250, 0.45)'
              : '1px solid rgba(196, 181, 253, 0.5)',
            borderRadius: '1rem',
            boxShadow: theme === 'original'
              ? '0 10px 25px rgba(37, 99, 235, 0.22)'
              : '0 10px 25px rgba(196, 181, 253, 0.3)',
          },
          success: {
            iconTheme: {
              primary: theme === 'original' ? '#2563eb' : '#a855f7',
              secondary: theme === 'original' ? '#dbeafe' : '#fdf2f8',
            },
          },
          error: {
            iconTheme: {
              primary: '#ec4899',
              secondary: '#fdf2f8',
            },
          },
        }} 
      />
    </div>
  );
}

function AppRouter() {
  return (
    <Routes>
      {/* Trigger page - public, uses feed token auth, no session required */}
      <Route path="/trigger" element={<TriggerPage />} />
      {/* All other routes go through AppShell */}
      <Route path="/*" element={<AppShell />} />
    </Routes>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <AudioPlayerProvider>
            <Router>
              <AppRouter />
            </Router>
          </AudioPlayerProvider>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
