import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AudioPlayerProvider } from './contexts/AudioPlayerContext';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { ThemeProvider } from './contexts/ThemeContext';
import Sidebar from './components/layout/Sidebar';
import DashboardPage from './pages/DashboardPage';
import PodcastsPage from './pages/PodcastsPage';
import JobsPage from './pages/JobsPage';
import PresetsPage from './pages/PresetsPage';
import ConfigPage from './pages/ConfigPage';
import LoginPage from './pages/LoginPage';
import SubscriptionsPage from './pages/SubscriptionsPage';
import AudioPlayer from './components/AudioPlayer';
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
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

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
    return <LoginPage />;
  }

  const showSettingsRoute = !requireAuth || user?.role === 'admin';

  return (
    <div className="h-screen flex overflow-hidden bg-gray-100">
      {/* Mobile Header */}
      <div className="lg:hidden fixed top-0 left-0 right-0 z-40 h-14 bg-gradient-to-r from-purple-800 via-purple-900 to-slate-900 flex items-center px-4 shadow-lg">
        <button
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="p-2 rounded-lg text-white hover:bg-purple-700/50"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {mobileMenuOpen ? (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            )}
          </svg>
        </button>
        <span className="ml-3 text-lg font-bold rainbow-text">Podly Unicorn</span>
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
        fixed lg:relative z-40 lg:z-auto
        transform lg:transform-none transition-transform duration-300
        ${mobileMenuOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        top-14 lg:top-0 bottom-0 lg:bottom-auto lg:h-full
      `}>
        <Sidebar 
          collapsed={sidebarCollapsed} 
          onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
          onNavigate={() => setMobileMenuOpen(false)}
          isMobile={mobileMenuOpen}
        />
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden pt-14 lg:pt-0">
        <main className="flex-1 overflow-auto p-3 sm:p-4 lg:p-6">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/podcasts" element={<PodcastsPage />} />
            <Route path="/jobs" element={<JobsPage />} />
            {showSettingsRoute && <Route path="/subscriptions" element={<SubscriptionsPage />} />}
            {showSettingsRoute && <Route path="/presets" element={<PresetsPage />} />}
            {showSettingsRoute && <Route path="/settings" element={<ConfigPage />} />}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>

        <AudioPlayer />
      </div>

      <Toaster 
        position="top-center" 
        toastOptions={{ 
          duration: 3000,
          style: {
            background: 'linear-gradient(135deg, #fdf2f8 0%, #f3e8ff 50%, #ecfeff 100%)',
            color: '#581c87',
            border: '1px solid rgba(196, 181, 253, 0.5)',
            borderRadius: '1rem',
            boxShadow: '0 10px 25px rgba(196, 181, 253, 0.3)',
          },
          success: {
            iconTheme: {
              primary: '#a855f7',
              secondary: '#fdf2f8',
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

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <AudioPlayerProvider>
            <Router>
              <AppShell />
            </Router>
          </AudioPlayerProvider>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
