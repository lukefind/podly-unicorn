import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AudioPlayerProvider } from './contexts/AudioPlayerContext';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import Sidebar from './components/layout/Sidebar';
import DashboardPage from './pages/DashboardPage';
import PodcastsPage from './pages/PodcastsPage';
import JobsPage from './pages/JobsPage';
import PresetsPage from './pages/PresetsPage';
import ConfigPage from './pages/ConfigPage';
import LoginPage from './pages/LoginPage';
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
      {/* Sidebar */}
      <Sidebar 
        collapsed={sidebarCollapsed} 
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)} 
      />

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <main className="flex-1 overflow-auto p-6">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/podcasts" element={<PodcastsPage />} />
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/presets" element={<PresetsPage />} />
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
      <AuthProvider>
        <AudioPlayerProvider>
          <Router>
            <AppShell />
          </Router>
        </AudioPlayerProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;
