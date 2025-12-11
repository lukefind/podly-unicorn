import { useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import { feedsApi } from '../services/api';
import { useTheme } from '../contexts/ThemeContext';

interface ProcessingStatsButtonProps {
  episodeGuid: string;
  hasProcessedAudio: boolean;
  className?: string;
}

export default function ProcessingStatsButton({
  episodeGuid,
  hasProcessedAudio,
  className = ''
}: ProcessingStatsButtonProps) {
  const [showModal, setShowModal] = useState(false);
  const [activeTab, setActiveTab] = useState<'overview' | 'model-calls' | 'transcript' | 'identifications'>('overview');
  const [expandedModelCalls, setExpandedModelCalls] = useState<Set<number>>(new Set());
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['episode-stats', episodeGuid],
    queryFn: () => feedsApi.getPostStats(episodeGuid),
    enabled: showModal && hasProcessedAudio, // Only fetch when modal is open and episode is processed
  });

  const formatDuration = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.round(seconds % 60); // Round to nearest whole second

    if (hours > 0) {
      return `${hours}h ${minutes}m ${secs}s`;
    }
    return `${minutes}m ${secs}s`;
  };

  const formatTimeHMS = (seconds: number) => {
    if (seconds == null || isNaN(seconds)) return '0:00';
    const s = Math.floor(seconds);
    const hours = Math.floor(s / 3600);
    const minutes = Math.floor((s % 3600) / 60);
    const secs = s % 60;

    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
  };

  const formatTimestamp = (timestamp: string | null) => {
    if (!timestamp) return 'N/A';
    return new Date(timestamp).toLocaleString();
  };

  const toggleModelCallDetails = (callId: number) => {
    const newExpanded = new Set(expandedModelCalls);
    if (newExpanded.has(callId)) {
      newExpanded.delete(callId);
    } else {
      newExpanded.add(callId);
    }
    setExpandedModelCalls(newExpanded);
  };

  if (!hasProcessedAudio) {
    return null;
  }

  return (
    <>
      <button
        onClick={() => setShowModal(true)}
        className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all border bg-white border-purple-200 text-purple-600 hover:bg-purple-50 flex items-center gap-1.5 ${className}`}
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
        Stats
      </button>

      {/* Modal - rendered via portal to document.body */}
      {showModal && createPortal(
        <div 
          className="fixed inset-0 bg-purple-900/60 backdrop-blur-sm flex items-center justify-center p-2 sm:p-4"
          style={{ zIndex: 9999 }}
          onClick={() => setShowModal(false)}
        >
          <div 
            className="modal-content rounded-xl sm:rounded-2xl max-w-6xl w-full max-h-[95vh] sm:max-h-[90vh] overflow-hidden shadow-2xl border"
            style={{ 
              backgroundColor: isDark ? '#1a0f2e' : '#ffffff',
              borderColor: isDark ? 'rgba(139, 92, 246, 0.3)' : 'rgba(196, 181, 253, 0.5)'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div 
              className="flex items-center justify-between p-4 sm:p-6 border-b"
              style={{ 
                backgroundColor: isDark ? 'rgba(30, 20, 50, 0.8)' : undefined,
                borderColor: isDark ? 'rgba(139, 92, 246, 0.2)' : 'rgba(243, 232, 255, 1)',
                background: isDark ? 'linear-gradient(to right, rgba(30, 10, 40, 0.9), rgba(20, 10, 50, 0.9), rgba(10, 20, 40, 0.9))' : 'linear-gradient(to right, #fdf2f8, #faf5ff, #ecfeff)'
              }}
            >
              <h2 className="text-base sm:text-xl font-bold text-left" style={{ color: isDark ? '#e9d5ff' : '#581c87' }}>Processing Stats</h2>
              <button
                onClick={() => setShowModal(false)}
                className="p-2 rounded-lg transition-colors"
                style={{ color: isDark ? '#a78bfa' : '#a855f7' }}
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Tabs */}
            <div 
              className="border-b overflow-x-auto"
              style={{ 
                backgroundColor: isDark ? 'rgba(25, 15, 45, 0.9)' : '#faf5ff',
                borderColor: isDark ? 'rgba(139, 92, 246, 0.2)' : 'rgba(243, 232, 255, 1)'
              }}
            >
              <nav className="flex space-x-2 sm:space-x-8 px-3 sm:px-6 min-w-max">
                {[
                  { id: 'overview', label: 'Overview' },
                  { id: 'model-calls', label: 'Model Calls' },
                  { id: 'transcript', label: 'Transcript Segments' },
                  { id: 'identifications', label: 'Identifications' }
                ].map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id as 'overview' | 'model-calls' | 'transcript' | 'identifications')}
                    className={`py-3 sm:py-4 px-2 sm:px-1 border-b-2 font-medium text-xs sm:text-sm transition-colors whitespace-nowrap ${
                      activeTab === tab.id
                        ? 'border-purple-500'
                        : 'border-transparent hover:border-purple-300'
                    }`}
                    style={{ color: activeTab === tab.id ? (isDark ? '#c4b5fd' : '#6b21a8') : (isDark ? '#a78bfa' : '#6b7280') }}
                  >
                    <span className="hidden sm:inline">{tab.label}</span>
                    <span className="sm:hidden">{tab.id === 'model-calls' ? 'Calls' : tab.id === 'identifications' ? 'IDs' : tab.label}</span>
                    {stats && tab.id === 'model-calls' && stats.model_calls && ` (${stats.model_calls.length})`}
                    {stats && tab.id === 'transcript' && stats.transcript_segments && ` (${stats.transcript_segments.length})`}
                    {stats && tab.id === 'identifications' && stats.identifications && ` (${stats.identifications.length})`}
                  </button>
                ))}
              </nav>
            </div>

            {/* Content */}
            <div 
              className="p-3 sm:p-6 overflow-y-auto max-h-[calc(95vh-140px)] sm:max-h-[calc(90vh-200px)]" 
              style={{ backgroundColor: isDark ? '#1a0f2e' : '#ffffff' }}
            >
              {isLoading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-600"></div>
                  <span className="ml-3" style={{ color: '#4b5563' }}>Loading stats...</span>
                </div>
              ) : error ? (
                <div className="text-center py-12">
                  <p className="text-red-600">Failed to load processing statistics</p>
                </div>
              ) : stats ? (
                <>
                  {/* Overview Tab */}
                  {activeTab === 'overview' && (
                    <div className="space-y-6">
                      {/* Episode Title */}
                      <div className="text-left">
                        <h3 className="text-lg font-semibold text-gray-900">{stats.post?.title || 'Unknown Episode'}</h3>
                        <p className="text-sm text-gray-500 mt-1">
                          {stats.post?.release_date ? new Date(stats.post.release_date).toLocaleDateString() : ''}
                        </p>
                      </div>

                      {/* Duration Comparison - Hero Section */}
                      <div className="bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 rounded-xl p-4 sm:p-6 text-white">
                        <h3 className="text-xs sm:text-sm font-medium opacity-90 mb-3 sm:mb-4">Duration Comparison</h3>
                        <div className="grid grid-cols-3 gap-2 sm:gap-4">
                          <div className="text-center">
                            <div className="text-lg sm:text-3xl font-bold">
                              {stats.post?.duration ? formatDuration(stats.post.duration) : '--'}
                            </div>
                            <div className="text-xs sm:text-sm opacity-80 mt-1">Original</div>
                          </div>
                          <div className="text-center flex flex-col items-center justify-center">
                            <div className="text-lg sm:text-2xl">→</div>
                            <div className="text-sm sm:text-lg font-semibold text-green-200">
                              -{stats.processing_stats?.estimated_ad_time_seconds ? formatDuration(stats.processing_stats.estimated_ad_time_seconds) : '0m 0s'}
                            </div>
                          </div>
                          <div className="text-center">
                            <div className="text-lg sm:text-3xl font-bold">
                              {stats.post?.duration && stats.processing_stats?.estimated_ad_time_seconds 
                                ? formatDuration(stats.post.duration - stats.processing_stats.estimated_ad_time_seconds)
                                : stats.post?.duration ? formatDuration(stats.post.duration) : '--'}
                            </div>
                            <div className="text-xs sm:text-sm opacity-80 mt-1">After Ads</div>
                          </div>
                        </div>
                        {stats.post?.duration && stats.processing_stats?.estimated_ad_time_seconds && (
                          <div className="mt-4 pt-4 border-t border-white/20">
                            <div className="flex justify-between items-center">
                              <span className="text-sm opacity-80">Ads removed</span>
                              <span className="text-lg font-semibold">
                                {((stats.processing_stats.estimated_ad_time_seconds / stats.post.duration) * 100).toFixed(1)}%
                              </span>
                            </div>
                            <div className="mt-2 h-2 bg-white/20 rounded-full overflow-hidden">
                              <div 
                                className="h-full bg-green-300 rounded-full transition-all"
                                style={{ width: `${100 - (stats.processing_stats.estimated_ad_time_seconds / stats.post.duration) * 100}%` }}
                              />
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Key Metrics - Clickable to navigate to relevant tabs */}
                      <div className="grid grid-cols-2 gap-2 sm:gap-4">
                        <button 
                          onClick={() => setActiveTab('transcript')}
                          className="rounded-xl p-3 sm:p-4 text-center shadow-sm border cursor-pointer transition-all hover:scale-105 hover:shadow-md"
                          style={{ 
                            backgroundColor: isDark ? 'rgba(139, 92, 246, 0.15)' : '#faf5ff',
                            borderColor: isDark ? 'rgba(139, 92, 246, 0.3)' : '#e9d5ff'
                          }}
                        >
                          <div className="text-2xl sm:text-3xl font-bold" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>
                            {stats.processing_stats?.total_segments || 0}
                          </div>
                          <div className="text-xs sm:text-sm mt-1" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Segments</div>
                        </button>

                        <button 
                          onClick={() => setActiveTab('transcript')}
                          className="rounded-xl p-3 sm:p-4 text-center shadow-sm border cursor-pointer transition-all hover:scale-105 hover:shadow-md"
                          style={{ 
                            backgroundColor: isDark ? 'rgba(34, 197, 94, 0.15)' : '#f0fdf4',
                            borderColor: isDark ? 'rgba(34, 197, 94, 0.3)' : '#bbf7d0'
                          }}
                        >
                          <div className="text-2xl sm:text-3xl font-bold" style={{ color: isDark ? '#86efac' : '#16a34a' }}>
                            {stats.processing_stats?.content_segments || 0}
                          </div>
                          <div className="text-xs sm:text-sm mt-1" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Kept</div>
                        </button>

                        <button 
                          onClick={() => setActiveTab('identifications')}
                          className="rounded-xl p-3 sm:p-4 text-center shadow-sm border cursor-pointer transition-all hover:scale-105 hover:shadow-md"
                          style={{ 
                            backgroundColor: isDark ? 'rgba(239, 68, 68, 0.15)' : '#fef2f2',
                            borderColor: isDark ? 'rgba(239, 68, 68, 0.3)' : '#fecaca'
                          }}
                        >
                          <div className="text-2xl sm:text-3xl font-bold" style={{ color: isDark ? '#fca5a5' : '#dc2626' }}>
                            {stats.processing_stats?.ad_segments_count || 0}
                          </div>
                          <div className="text-xs sm:text-sm mt-1" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Ads</div>
                        </button>

                        <button 
                          onClick={() => setActiveTab('model-calls')}
                          className="rounded-xl p-3 sm:p-4 text-center shadow-sm border cursor-pointer transition-all hover:scale-105 hover:shadow-md"
                          style={{ 
                            backgroundColor: isDark ? 'rgba(139, 92, 246, 0.15)' : '#faf5ff',
                            borderColor: isDark ? 'rgba(139, 92, 246, 0.3)' : '#e9d5ff'
                          }}
                        >
                          <div className="text-2xl sm:text-3xl font-bold" style={{ color: isDark ? '#c4b5fd' : '#9333ea' }}>
                            {stats.processing_stats?.total_model_calls || 0}
                          </div>
                          <div className="text-xs sm:text-sm mt-1" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>AI Calls</div>
                        </button>
                      </div>

                      {/* Model Performance */}
                      <div className="grid grid-cols-1 gap-3 sm:gap-4">
                        {/* Model Call Status */}
                        <div 
                          className="rounded-xl p-4 sm:p-5 shadow-sm border"
                          style={{ 
                            backgroundColor: isDark ? 'rgba(139, 92, 246, 0.15)' : '#faf5ff',
                            borderColor: isDark ? 'rgba(139, 92, 246, 0.3)' : '#e9d5ff'
                          }}
                        >
                          <h4 className="font-semibold mb-3 sm:mb-4 text-left text-sm sm:text-base" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>Processing Status</h4>
                          <div className="space-y-3">
                            {Object.entries(stats.processing_stats?.model_call_statuses || {}).map(([status, count]) => (
                              <div key={status} className="flex justify-between items-center">
                                <span className="text-sm capitalize" style={{ color: isDark ? '#c4b5fd' : '#4b5563' }}>{status}</span>
                                <span
                                  className="px-3 py-1 rounded-full text-xs font-semibold"
                                  style={{
                                    backgroundColor: status === 'success' 
                                      ? (isDark ? 'rgba(34, 197, 94, 0.3)' : '#dcfce7')
                                      : status === 'failed' 
                                        ? (isDark ? 'rgba(239, 68, 68, 0.3)' : '#fee2e2')
                                        : (isDark ? 'rgba(107, 114, 128, 0.3)' : '#f3f4f6'),
                                    color: status === 'success'
                                      ? (isDark ? '#86efac' : '#15803d')
                                      : status === 'failed'
                                        ? (isDark ? '#fca5a5' : '#b91c1c')
                                        : (isDark ? '#d1d5db' : '#374151')
                                  }}
                                >
                                  {count}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>

                        {/* Model Types */}
                        <div 
                          className="rounded-xl p-4 sm:p-5 shadow-sm border"
                          style={{ 
                            backgroundColor: isDark ? 'rgba(139, 92, 246, 0.15)' : '#faf5ff',
                            borderColor: isDark ? 'rgba(139, 92, 246, 0.3)' : '#e9d5ff'
                          }}
                        >
                          <h4 className="font-semibold mb-3 sm:mb-4 text-left text-sm sm:text-base" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>Models Used</h4>
                          <div className="space-y-3">
                            {Object.entries(stats.processing_stats?.model_types || {}).map(([model, count]) => (
                              <div key={model} className="flex justify-between items-center">
                                <span className="text-sm truncate max-w-[200px]" style={{ color: isDark ? '#c4b5fd' : '#4b5563' }} title={model}>{model}</span>
                                <span 
                                  className="px-3 py-1 rounded-full text-xs font-semibold"
                                  style={{
                                    backgroundColor: isDark ? 'rgba(139, 92, 246, 0.3)' : '#f3e8ff',
                                    color: isDark ? '#c4b5fd' : '#7c3aed'
                                  }}
                                >
                                  {count} calls
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>

                      {/* Preset Used for Processing */}
                      {stats.post?.processed_with_preset && (
                        <div 
                          className="rounded-xl p-5 shadow-sm border"
                          style={{ 
                            backgroundColor: isDark ? 'rgba(6, 182, 212, 0.15)' : '#ecfeff',
                            borderColor: isDark ? 'rgba(6, 182, 212, 0.3)' : '#a5f3fc'
                          }}
                        >
                          <h4 className="font-semibold mb-3 text-left" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>Preset Used for This Episode</h4>
                          <div className="flex items-center gap-4">
                            <div className="flex-1">
                              <div className="text-lg font-medium" style={{ color: isDark ? '#67e8f9' : '#0e7490' }}>
                                {stats.post.processed_with_preset.name}
                              </div>
                              <div className="text-sm mt-1" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>
                                Aggressiveness: <span className="font-medium capitalize">{stats.post.processed_with_preset.aggressiveness}</span>
                                {' · '}
                                Min Confidence: <span className="font-medium">{(stats.post.processed_with_preset.min_confidence * 100).toFixed(0)}%</span>
                              </div>
                            </div>
                            <div 
                              className="px-3 py-1 rounded-full text-xs font-semibold"
                              style={{
                                backgroundColor: stats.post.processed_with_preset.aggressiveness === 'conservative' 
                                  ? (isDark ? 'rgba(34, 197, 94, 0.3)' : '#dcfce7')
                                  : stats.post.processed_with_preset.aggressiveness === 'balanced' 
                                    ? (isDark ? 'rgba(234, 179, 8, 0.3)' : '#fef3c7')
                                    : stats.post.processed_with_preset.aggressiveness === 'aggressive' 
                                      ? (isDark ? 'rgba(249, 115, 22, 0.3)' : '#ffedd5')
                                      : (isDark ? 'rgba(239, 68, 68, 0.3)' : '#fee2e2'),
                                color: stats.post.processed_with_preset.aggressiveness === 'conservative'
                                  ? (isDark ? '#86efac' : '#15803d')
                                  : stats.post.processed_with_preset.aggressiveness === 'balanced'
                                    ? (isDark ? '#fde047' : '#a16207')
                                    : stats.post.processed_with_preset.aggressiveness === 'aggressive'
                                      ? (isDark ? '#fdba74' : '#c2410c')
                                      : (isDark ? '#fca5a5' : '#b91c1c')
                              }}
                            >
                              {stats.post.processed_with_preset.aggressiveness}
                            </div>
                          </div>
                        </div>
                      )}
                      {!stats.post?.processed_with_preset && stats.post?.has_processed_audio && (
                        <div 
                          className="rounded-xl p-5 shadow-sm border"
                          style={{ 
                            backgroundColor: isDark ? 'rgba(107, 114, 128, 0.15)' : '#f9fafb',
                            borderColor: isDark ? 'rgba(107, 114, 128, 0.3)' : '#e5e7eb'
                          }}
                        >
                          <h4 className="font-semibold mb-2 text-left" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>Preset Used for This Episode</h4>
                          <p className="text-sm" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>
                            Processed before preset tracking was added, or using default prompts.
                          </p>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Model Calls Tab */}
                  {activeTab === 'model-calls' && (
                    <div>
                      <h3 className="font-semibold mb-4 text-left" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>Model Calls ({stats.model_calls?.length || 0})</h3>
                      <div 
                        className="border rounded-lg overflow-hidden"
                        style={{ 
                          backgroundColor: isDark ? 'rgba(25, 15, 45, 0.5)' : '#ffffff',
                          borderColor: isDark ? 'rgba(139, 92, 246, 0.3)' : '#e5e7eb'
                        }}
                      >
                        <div className="overflow-x-auto">
                          <table className="min-w-full">
                            <thead style={{ backgroundColor: isDark ? 'rgba(30, 20, 50, 0.8)' : '#f9fafb' }}>
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>ID</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Model</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Segment Range</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Status</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Timestamp</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Retries</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Actions</th>
                              </tr>
                            </thead>
                            <tbody>
                              {(stats.model_calls || []).map((call, idx) => (
                                <>
                                  <tr 
                                    key={call.id}
                                    style={{ 
                                      backgroundColor: idx % 2 === 0 ? (isDark ? 'rgba(25, 15, 45, 0.3)' : '#ffffff') : (isDark ? 'rgba(30, 20, 50, 0.3)' : '#f9fafb'),
                                      borderBottom: isDark ? '1px solid rgba(139, 92, 246, 0.1)' : '1px solid #e5e7eb'
                                    }}
                                  >
                                    <td className="px-4 py-3 text-sm" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>{call.id}</td>
                                    <td className="px-4 py-3 text-sm" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>{call.model_name}</td>
                                    <td className="px-4 py-3 text-sm" style={{ color: isDark ? '#c4b5fd' : '#4b5563' }}>{call.segment_range}</td>
                                    <td className="px-4 py-3">
                                      <span 
                                        className="inline-flex px-2 py-1 text-xs font-medium rounded-full"
                                        style={{
                                          backgroundColor: call.status === 'success' 
                                            ? (isDark ? 'rgba(34, 197, 94, 0.3)' : '#dcfce7')
                                            : call.status === 'failed' 
                                              ? (isDark ? 'rgba(239, 68, 68, 0.3)' : '#fee2e2')
                                              : (isDark ? 'rgba(234, 179, 8, 0.3)' : '#fef3c7'),
                                          color: call.status === 'success'
                                            ? (isDark ? '#86efac' : '#166534')
                                            : call.status === 'failed'
                                              ? (isDark ? '#fca5a5' : '#991b1b')
                                              : (isDark ? '#fde047' : '#92400e')
                                        }}
                                      >
                                        {call.status}
                                      </span>
                                    </td>
                                    <td className="px-4 py-3 text-sm" style={{ color: isDark ? '#c4b5fd' : '#4b5563' }}>{formatTimestamp(call.timestamp)}</td>
                                    <td className="px-4 py-3 text-sm" style={{ color: isDark ? '#c4b5fd' : '#4b5563' }}>{call.retry_attempts}</td>
                                    <td className="px-4 py-3">
                                      <button
                                        onClick={() => toggleModelCallDetails(call.id)}
                                        className="text-sm font-medium"
                                        style={{ color: isDark ? '#a78bfa' : '#2563eb' }}
                                      >
                                        {expandedModelCalls.has(call.id) ? 'Hide' : 'Details'}
                                      </button>
                                    </td>
                                  </tr>
                                  {expandedModelCalls.has(call.id) && (
                                    <tr style={{ backgroundColor: isDark ? 'rgba(30, 20, 50, 0.5)' : '#f9fafb' }}>
                                      <td colSpan={7} className="px-4 py-4">
                                        <div className="space-y-4">
                                          {call.prompt && (
                                            <div>
                                              <h5 className="font-medium text-gray-900 mb-2 text-left">Prompt:</h5>
                                              <div className="bg-gray-100 p-3 rounded text-sm font-mono whitespace-pre-wrap max-h-40 overflow-y-auto text-left">
                                                {call.prompt}
                                              </div>
                                            </div>
                                          )}
                                          {call.error_message && (
                                            <div>
                                              <h5 className="font-medium text-red-900 mb-2 text-left">Error Message:</h5>
                                              <div className="bg-red-50 p-3 rounded text-sm font-mono whitespace-pre-wrap text-left">
                                                {call.error_message}
                                              </div>
                                            </div>
                                          )}
                                          {call.response && (
                                            <div>
                                              <h5 className="font-medium text-gray-900 mb-2 text-left">Response:</h5>
                                              <div className="bg-gray-100 p-3 rounded text-sm font-mono whitespace-pre-wrap max-h-40 overflow-y-auto text-left">
                                                {call.response}
                                              </div>
                                            </div>
                                          )}
                                        </div>
                                      </td>
                                    </tr>
                                  )}
                                </>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Transcript Segments Tab */}
                  {activeTab === 'transcript' && (
                    <div>
                      <h3 className="font-semibold mb-4 text-left" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>Transcript Segments ({stats.transcript_segments?.length || 0})</h3>
                      <div 
                        className="border rounded-lg overflow-hidden"
                        style={{ 
                          backgroundColor: isDark ? 'rgba(25, 15, 45, 0.5)' : '#ffffff',
                          borderColor: isDark ? 'rgba(139, 92, 246, 0.3)' : '#e5e7eb'
                        }}
                      >
                        <div className="overflow-x-auto">
                          <table className="min-w-full">
                            <thead style={{ backgroundColor: isDark ? 'rgba(30, 20, 50, 0.8)' : '#f9fafb' }}>
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Seq #</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Time Range</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Label</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Text</th>
                              </tr>
                            </thead>
                            <tbody>
                              {(stats.transcript_segments || []).map((segment, idx) => (
                                <tr 
                                  key={segment.id} 
                                  style={{ 
                                    backgroundColor: segment.primary_label === 'ad' 
                                      ? (isDark ? 'rgba(159, 18, 57, 0.2)' : '#fef2f2')
                                      : (idx % 2 === 0 ? (isDark ? 'rgba(25, 15, 45, 0.3)' : '#ffffff') : (isDark ? 'rgba(30, 20, 50, 0.3)' : '#f9fafb')),
                                    borderBottom: isDark ? '1px solid rgba(139, 92, 246, 0.1)' : '1px solid #e5e7eb'
                                  }}
                                >
                                  <td className="px-4 py-3 text-sm" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>{segment.sequence_num}</td>
                                  <td className="px-4 py-3 text-sm" style={{ color: isDark ? '#c4b5fd' : '#374151' }}>
                                    {formatTimeHMS(segment.start_time)} - {formatTimeHMS(segment.end_time)}
                                  </td>
                                  <td className="px-4 py-3">
                                    <span 
                                      className="inline-flex px-2 py-1 text-xs font-medium rounded-full"
                                      style={{
                                        backgroundColor: segment.primary_label === 'ad'
                                          ? (isDark ? 'rgba(244, 63, 94, 0.3)' : '#ffe4e6')
                                          : (isDark ? 'rgba(34, 197, 94, 0.3)' : '#d1fae5'),
                                        color: segment.primary_label === 'ad'
                                          ? (isDark ? '#fda4af' : '#9f1239')
                                          : (isDark ? '#86efac' : '#065f46')
                                      }}
                                    >
                                      {segment.primary_label === 'ad' ? 'Ad' : 'Content'}
                                    </span>
                                  </td>
                                  <td className="px-4 py-3 text-sm max-w-md" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>
                                    <div className="truncate text-left" title={segment.text}>
                                      {segment.text}
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Identifications Tab */}
                  {activeTab === 'identifications' && (
                    <div>
                      <h3 className="font-semibold mb-4 text-left" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>Identifications ({stats.identifications?.length || 0})</h3>
                      <div 
                        className="border rounded-lg overflow-hidden"
                        style={{ 
                          backgroundColor: isDark ? 'rgba(25, 15, 45, 0.5)' : '#ffffff',
                          borderColor: isDark ? 'rgba(139, 92, 246, 0.3)' : '#e5e7eb'
                        }}
                      >
                        <div className="overflow-x-auto">
                          <table className="min-w-full">
                            <thead style={{ backgroundColor: isDark ? 'rgba(30, 20, 50, 0.8)' : '#f9fafb' }}>
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>ID</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Segment ID</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Time Range</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Label</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Confidence</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Model Call</th>
                                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style={{ color: isDark ? '#a78bfa' : '#6b7280' }}>Text</th>
                              </tr>
                            </thead>
                            <tbody>
                              {(stats.identifications || []).map((identification, idx) => (
                                <tr
                                  key={identification.id}
                                  style={{ 
                                    backgroundColor: identification.label === 'ad' 
                                      ? (isDark ? 'rgba(159, 18, 57, 0.2)' : '#fef2f2')
                                      : (idx % 2 === 0 ? (isDark ? 'rgba(25, 15, 45, 0.3)' : '#ffffff') : (isDark ? 'rgba(30, 20, 50, 0.3)' : '#f9fafb')),
                                    borderBottom: isDark ? '1px solid rgba(139, 92, 246, 0.1)' : '1px solid #e5e7eb'
                                  }}
                                >
                                  <td className="px-4 py-3 text-sm" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>{identification.id}</td>
                                  <td className="px-4 py-3 text-sm" style={{ color: isDark ? '#c4b5fd' : '#4b5563' }}>{identification.transcript_segment_id}</td>
                                  <td className="px-4 py-3 text-sm" style={{ color: isDark ? '#c4b5fd' : '#374151' }}>
                                    {formatTimeHMS(identification.segment_start_time)} - {formatTimeHMS(identification.segment_end_time)}
                                  </td>
                                  <td className="px-4 py-3">
                                    <span 
                                      className="inline-flex px-2 py-1 text-xs font-medium rounded-full"
                                      style={{
                                        backgroundColor: identification.label === 'ad'
                                          ? (isDark ? 'rgba(244, 63, 94, 0.3)' : '#ffe4e6')
                                          : (isDark ? 'rgba(34, 197, 94, 0.3)' : '#d1fae5'),
                                        color: identification.label === 'ad'
                                          ? (isDark ? '#fda4af' : '#9f1239')
                                          : (isDark ? '#86efac' : '#065f46')
                                      }}
                                    >
                                      {identification.label}
                                    </span>
                                  </td>
                                  <td className="px-4 py-3 text-sm" style={{ color: isDark ? '#c4b5fd' : '#4b5563' }}>
                                    {identification.confidence ? identification.confidence.toFixed(2) : 'N/A'}
                                  </td>
                                  <td className="px-4 py-3 text-sm" style={{ color: isDark ? '#c4b5fd' : '#4b5563' }}>{identification.model_call_id}</td>
                                  <td className="px-4 py-3 text-sm max-w-md" style={{ color: isDark ? '#e9d5ff' : '#1f2937' }}>
                                    <div className="truncate text-left" title={identification.segment_text}>
                                      {identification.segment_text}
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  )}

                </>
              ) : null}
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
