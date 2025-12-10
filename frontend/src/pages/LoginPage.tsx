import type { FormEvent } from 'react';
import { useState } from 'react';
import axios from 'axios';
import { useAuth } from '../contexts/AuthContext';

export default function LoginPage() {
  const { login } = useAuth();
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
    <div className="min-h-screen bg-gradient-to-br from-pink-50 via-purple-50 to-cyan-50 flex items-center justify-center px-4">
      {/* Decorative background elements */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-pink-200/30 to-purple-200/30 rounded-full blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-gradient-to-br from-cyan-200/30 to-purple-200/30 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-md bg-white/80 backdrop-blur-sm shadow-xl rounded-2xl border border-purple-100 p-8">
        <div className="flex flex-col items-center gap-3 mb-8">
          <div className="relative">
            <div className="absolute inset-0 bg-gradient-to-r from-pink-400 via-purple-400 to-cyan-400 rounded-full blur-lg opacity-30" />
            <img 
              src="/images/logos/unicorn-logo.png" 
              alt="Podly Unicorn" 
              className="relative h-20 w-20 object-contain"
            />
          </div>
          <h1 className="text-2xl font-bold bg-gradient-to-r from-pink-600 via-purple-600 to-cyan-600 bg-clip-text text-transparent">
            Podly Unicorn
          </h1>
          <p className="text-sm text-purple-600/70">Sign in to continue</p>
        </div>

        <form className="space-y-5" onSubmit={handleSubmit}>
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-purple-700 mb-1">
              Username
            </label>
            <input
              id="username"
              name="username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="block w-full rounded-xl border border-purple-200 bg-white/50 px-4 py-3 shadow-sm focus:border-purple-400 focus:outline-none focus:ring-2 focus:ring-purple-400/20 transition-all"
              placeholder="Enter your username"
              disabled={submitting}
              required
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-purple-700 mb-1">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="block w-full rounded-xl border border-purple-200 bg-white/50 px-4 py-3 shadow-sm focus:border-purple-400 focus:outline-none focus:ring-2 focus:ring-purple-400/20 transition-all"
              placeholder="Enter your password"
              disabled={submitting}
              required
            />
          </div>

          {error && (
            <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 flex items-center gap-2">
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

        <div className="mt-6 text-center">
          <p className="text-xs text-purple-400">
            🦄 Podly Unicorn — Ad-free podcasts
          </p>
        </div>
      </div>
    </div>
  );
}
