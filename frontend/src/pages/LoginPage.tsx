import type { FormEvent } from 'react';
import { useState } from 'react';
import axios from 'axios';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';

export default function LoginPage() {
  const { login } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      await login(username, password);
      setUsername('');
      setPassword('');
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const message = err.response?.data?.error ?? 'Invalid username or password.';
        setError(message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Login failed. Please try again.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div 
      className="bg-gradient-to-br from-pink-50 via-purple-50 to-cyan-50 dark:from-slate-900 dark:via-purple-950 dark:to-slate-900"
      style={{ 
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        overflowY: 'auto',
        overflowX: 'hidden',
        WebkitOverflowScrolling: 'touch'
      }}
    >
      {/* Theme toggle button - fixed position */}
      <button
        onClick={toggleTheme}
        style={{ position: 'fixed', top: 16, right: 16, zIndex: 100 }}
        className="p-3 rounded-xl bg-white/80 dark:bg-slate-800/80 border border-purple-200 dark:border-purple-700 text-purple-600 dark:text-purple-300 shadow-lg"
        title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      >
        {theme === 'dark' ? (
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
          </svg>
        ) : (
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
          </svg>
        )}
      </button>

      <div className="max-w-5xl mx-auto px-4 py-8 flex flex-col md:flex-row gap-8 md:gap-12 items-start md:min-h-screen md:justify-center md:items-center">
        {/* Left side - Features */}
        <div className="flex-1 text-center md:text-left flex flex-col justify-center">
          <div className="flex items-center justify-center md:justify-start gap-3 mb-6">
            <div className="relative">
              <div className="absolute inset-0 bg-gradient-to-r from-pink-400 via-purple-400 to-cyan-400 rounded-full blur-lg opacity-40" />
              <img 
                src="/images/logos/unicorn-logo.png" 
                alt="Podly Unicorn" 
                className="relative h-16 w-16 object-contain"
              />
            </div>
            <h1 className="text-3xl md:text-4xl font-bold rainbow-text">
              Podly Unicorn
            </h1>
          </div>
          
          <p className="text-lg md:text-xl text-purple-700 dark:text-purple-300 mb-8 max-w-md mx-auto md:mx-0">
            Your personal podcast ad-removal system powered by AI. Enjoy your favorite shows without interruptions.
          </p>

          {/* Feature list - compact */}
          <div className="grid grid-cols-2 gap-3 max-w-md w-full mx-auto md:mx-0">
            <div className="flex items-start gap-3 bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm rounded-xl p-3 border border-purple-100 dark:border-purple-800 shadow-sm">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-pink-500 to-purple-500 flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                </svg>
              </div>
              <div>
                <h3 className="font-semibold text-purple-900 dark:text-purple-100 text-sm">AI-Powered</h3>
                <p className="text-xs text-purple-600 dark:text-purple-400">LLMs detect and remove ads</p>
              </div>
            </div>

            <div className="flex items-start gap-3 bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm rounded-xl p-3 border border-purple-100 dark:border-purple-800 shadow-sm">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-cyan-500 flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 5c7.18 0 13 5.82 13 13M6 11a7 7 0 017 7m-6 0a1 1 0 11-2 0 1 1 0 012 0z" />
                </svg>
              </div>
              <div>
                <h3 className="font-semibold text-purple-900 dark:text-purple-100 text-sm">RSS Feeds</h3>
                <p className="text-xs text-purple-600 dark:text-purple-400">Use any podcast app</p>
              </div>
            </div>

            <div className="flex items-start gap-3 bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm rounded-xl p-3 border border-purple-100 dark:border-purple-800 shadow-sm">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-emerald-500 flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                </svg>
              </div>
              <div>
                <h3 className="font-semibold text-purple-900 dark:text-purple-100 text-sm">Presets</h3>
                <p className="text-xs text-purple-600 dark:text-purple-400">Conservative to aggressive</p>
              </div>
            </div>

            <div className="flex items-start gap-3 bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm rounded-xl p-3 border border-purple-100 dark:border-purple-800 shadow-sm">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-orange-500 to-pink-500 flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
              </div>
              <div>
                <h3 className="font-semibold text-purple-900 dark:text-purple-100 text-sm">Statistics</h3>
                <p className="text-xs text-purple-600 dark:text-purple-400">Track ad time removed</p>
              </div>
            </div>
          </div>
        </div>

        {/* Right side - Login form */}
        <div className="w-full max-w-md bg-white/80 dark:bg-slate-800/80 backdrop-blur-sm shadow-xl rounded-2xl border border-purple-100 dark:border-purple-800 p-8 md:self-center">
          <div className="text-center mb-6">
            <h2 className="text-xl font-bold text-purple-900 dark:text-purple-100 mb-2">Welcome Back</h2>
            <p className="text-sm text-purple-600/70 dark:text-purple-300/70">Sign in to access your podcasts</p>
          </div>

          <form className="space-y-5" onSubmit={handleSubmit}>
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-purple-700 dark:text-purple-300 mb-1">
                Username
              </label>
              <input
                id="username"
                name="username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="block w-full rounded-xl border border-purple-200 dark:border-purple-700 bg-white/50 dark:bg-slate-700/50 px-4 py-3 shadow-sm focus:border-purple-400 focus:outline-none focus:ring-2 focus:ring-purple-400/20 transition-all dark:text-white dark:placeholder-purple-300/50"
                placeholder="Enter your username"
                disabled={submitting}
                required
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-purple-700 dark:text-purple-300 mb-1">
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="block w-full rounded-xl border border-purple-200 dark:border-purple-700 bg-white/50 dark:bg-slate-700/50 px-4 py-3 shadow-sm focus:border-purple-400 focus:outline-none focus:ring-2 focus:ring-purple-400/20 transition-all dark:text-white dark:placeholder-purple-300/50"
                placeholder="Enter your password"
                disabled={submitting}
                required
              />
            </div>

            {error && (
              <div className="rounded-xl bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300 flex items-center gap-2">
                <svg className="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full flex justify-center items-center gap-2 rounded-xl bg-gradient-to-r from-pink-500 via-purple-500 to-cyan-500 px-4 py-3 text-white font-semibold shadow-lg shadow-purple-500/25 hover:shadow-purple-500/40 hover:scale-[1.02] transition-all disabled:opacity-60 disabled:cursor-not-allowed disabled:hover:scale-100"
            >
              {submitting && <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />}
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          <div className="mt-6 pt-6 border-t border-purple-100 dark:border-purple-800">
            <div className="flex items-center justify-center gap-4 text-xs text-purple-400 dark:text-purple-500">
              <span className="flex items-center gap-1">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
                Secure
              </span>
              <span>•</span>
              <span className="flex items-center gap-1">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z" />
                </svg>
                Self-hosted
              </span>
              <span>•</span>
              <a 
                href="https://github.com/lukefind/podly-unicorn" 
                target="_blank" 
                rel="noopener noreferrer"
                className="flex items-center gap-1 hover:text-purple-600 dark:hover:text-purple-300 transition-colors"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
                </svg>
                GitHub
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
