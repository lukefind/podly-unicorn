import { useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { feedsApi, presetsApi } from '../services/api';
import { toast } from 'react-hot-toast';
import type { PromptPreset } from '../types';

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
  const [activeTab, setActiveTab] = useState<'overview' | 'model-calls' | 'transcript' | 'identifications' | 'settings'>('overview');
  const [expandedModelCalls, setExpandedModelCalls] = useState<Set<number>>(new Set());
  const [pendingPresetId, setPendingPresetId] = useState<number | null>(null);

  const queryClient = useQueryClient();

  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['episode-stats', episodeGuid],
    queryFn: () => feedsApi.getPostStats(episodeGuid),
    enabled: showModal && hasProcessedAudio, // Only fetch when modal is open and episode is processed
  });

  const { data: presets, isLoading: presetsLoading } = useQuery({
    queryKey: ['presets'],
    queryFn: presetsApi.getPresets,
    enabled: showModal,
  });

  const { data: statsSummary } = useQuery({
    queryKey: ['stats-summary'],
    queryFn: presetsApi.getStatsSummary,
    enabled: showModal,
  });

  const activatePresetMutation = useMutation({
    mutationFn: (presetId: number) => presetsApi.activatePreset(presetId),
    onSuccess: (data: { message: string }) => {
      toast.success(data.message);
      setPendingPresetId(null);
      queryClient.invalidateQueries({ queryKey: ['presets'] });
    },
    onError: () => {
      toast.error('Failed to activate preset');
      setPendingPresetId(null);
    },
  });

  const activePreset = presets?.find((p: PromptPreset) => p.is_active);

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
          className="fixed inset-0 bg-purple-900/60 backdrop-blur-sm flex items-center justify-center p-4"
          style={{ zIndex: 9999 }}
          onClick={() => setShowModal(false)}
        >
          <div 
            className="modal-content rounded-2xl max-w-6xl w-full max-h-[90vh] overflow-hidden shadow-2xl border border-purple-300"
            style={{ backgroundColor: '#ffffff' }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b border-purple-100 bg-gradient-to-r from-pink-50 via-purple-50 to-cyan-50">
              <h2 className="text-xl font-bold text-purple-900 text-left">Processing Statistics & Debug</h2>
              <button
                onClick={() => setShowModal(false)}
                className="p-2 text-purple-400 hover:text-purple-600 rounded-lg hover:bg-purple-100 transition-colors"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Tabs */}
            <div className="border-b border-purple-100" style={{ backgroundColor: '#faf5ff' }}>
              <nav className="flex space-x-8 px-6">
                {[
                  { id: 'overview', label: 'Overview' },
                  { id: 'model-calls', label: 'Model Calls' },
                  { id: 'transcript', label: 'Transcript Segments' },
                  { id: 'identifications', label: 'Identifications' },
                  { id: 'settings', label: 'Ad Detection Settings' }
                ].map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id as 'overview' | 'model-calls' | 'transcript' | 'identifications' | 'settings')}
                    className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                      activeTab === tab.id
                        ? 'border-purple-500 text-purple-700'
                        : 'border-transparent hover:border-purple-300'
                    }`}
                    style={{ color: activeTab === tab.id ? '#6b21a8' : '#6b7280' }}
                  >
                    {tab.label}
                    {stats && tab.id === 'model-calls' && stats.model_calls && ` (${stats.model_calls.length})`}
                    {stats && tab.id === 'transcript' && stats.transcript_segments && ` (${stats.transcript_segments.length})`}
                    {stats && tab.id === 'identifications' && stats.identifications && ` (${stats.identifications.length})`}
                  </button>
                ))}
              </nav>
            </div>

            {/* Content */}
            <div className="p-6 overflow-y-auto max-h-[calc(90vh-200px)]" style={{ backgroundColor: '#ffffff' }}>
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
                      <div className="bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 rounded-xl p-6 text-white">
                        <h3 className="text-sm font-medium opacity-90 mb-4">Duration Comparison</h3>
                        <div className="grid grid-cols-3 gap-4">
                          <div className="text-center">
                            <div className="text-3xl font-bold">
                              {stats.post?.duration ? formatDuration(stats.post.duration) : '--'}
                            </div>
                            <div className="text-sm opacity-80 mt-1">Original</div>
                          </div>
                          <div className="text-center flex flex-col items-center justify-center">
                            <div className="text-2xl">→</div>
                            <div className="text-lg font-semibold text-green-200">
                              -{stats.processing_stats?.estimated_ad_time_seconds ? formatDuration(stats.processing_stats.estimated_ad_time_seconds) : '0m 0s'}
                            </div>
                          </div>
                          <div className="text-center">
                            <div className="text-3xl font-bold">
                              {stats.post?.duration && stats.processing_stats?.estimated_ad_time_seconds 
                                ? formatDuration(stats.post.duration - stats.processing_stats.estimated_ad_time_seconds)
                                : stats.post?.duration ? formatDuration(stats.post.duration) : '--'}
                            </div>
                            <div className="text-sm opacity-80 mt-1">After Ad Removal</div>
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

                      {/* Key Metrics */}
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <div className="rounded-xl p-4 text-center shadow-sm border border-purple-200" style={{ backgroundColor: '#faf5ff' }}>
                          <div className="text-3xl font-bold" style={{ color: '#1f2937' }}>
                            {stats.processing_stats?.total_segments || 0}
                          </div>
                          <div className="text-sm mt-1" style={{ color: '#6b7280' }}>Total Segments</div>
                        </div>

                        <div className="rounded-xl p-4 text-center shadow-sm border border-green-200" style={{ backgroundColor: '#f0fdf4' }}>
                          <div className="text-3xl font-bold text-green-600">
                            {stats.processing_stats?.content_segments || 0}
                          </div>
                          <div className="text-sm mt-1" style={{ color: '#6b7280' }}>Content Kept</div>
                        </div>

                        <div className="rounded-xl p-4 text-center shadow-sm border border-red-200" style={{ backgroundColor: '#fef2f2' }}>
                          <div className="text-3xl font-bold text-red-600">
                            {stats.processing_stats?.ad_segments_count || 0}
                          </div>
                          <div className="text-sm mt-1" style={{ color: '#6b7280' }}>Ads Removed</div>
                        </div>

                        <div className="rounded-xl p-4 text-center shadow-sm border border-purple-200" style={{ backgroundColor: '#faf5ff' }}>
                          <div className="text-3xl font-bold text-purple-600">
                            {stats.processing_stats?.total_model_calls || 0}
                          </div>
                          <div className="text-sm mt-1" style={{ color: '#6b7280' }}>AI Calls</div>
                        </div>
                      </div>

                      {/* Model Performance */}
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Model Call Status */}
                        <div className="rounded-xl p-5 shadow-sm border border-purple-200" style={{ backgroundColor: '#faf5ff' }}>
                          <h4 className="font-semibold mb-4 text-left" style={{ color: '#1f2937' }}>Processing Status</h4>
                          <div className="space-y-3">
                            {Object.entries(stats.processing_stats?.model_call_statuses || {}).map(([status, count]) => (
                              <div key={status} className="flex justify-between items-center">
                                <span className="text-sm text-gray-600 capitalize">{status}</span>
                                <span
                                  className={`px-3 py-1 rounded-full text-xs font-semibold ${
                                    status === 'success' ? 'bg-green-100 text-green-700' :
                                    status === 'failed' ? 'bg-red-100 text-red-700' :
                                    'bg-gray-100 text-gray-700'
                                  }`}
                                >
                                  {count}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>

                        {/* Model Types */}
                        <div className="rounded-xl p-5 shadow-sm border border-purple-200" style={{ backgroundColor: '#faf5ff' }}>
                          <h4 className="font-semibold mb-4 text-left" style={{ color: '#1f2937' }}>Models Used</h4>
                          <div className="space-y-3">
                            {Object.entries(stats.processing_stats?.model_types || {}).map(([model, count]) => (
                              <div key={model} className="flex justify-between items-center">
                                <span className="text-sm truncate max-w-[200px]" style={{ color: '#4b5563' }} title={model}>{model}</span>
                                <span className="px-3 py-1 bg-purple-100 text-purple-700 rounded-full text-xs font-semibold">
                                  {count} calls
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Model Calls Tab */}
                  {activeTab === 'model-calls' && (
                    <div>
                      <h3 className="font-semibold text-gray-900 mb-4 text-left">Model Calls ({stats.model_calls?.length || 0})</h3>
                      <div className="bg-white border rounded-lg overflow-hidden">
                        <div className="overflow-x-auto">
                          <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Model</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Segment Range</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Timestamp</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Retries</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                              {(stats.model_calls || []).map((call) => (
                                <>
                                  <tr key={call.id} className="hover:bg-gray-50">
                                    <td className="px-4 py-3 text-sm text-gray-900">{call.id}</td>
                                    <td className="px-4 py-3 text-sm text-gray-900">{call.model_name}</td>
                                    <td className="px-4 py-3 text-sm text-gray-600">{call.segment_range}</td>
                                    <td className="px-4 py-3">
                                      <span className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                                        call.status === 'success' ? 'bg-green-100 text-green-800' :
                                        call.status === 'failed' ? 'bg-red-100 text-red-800' :
                                        'bg-yellow-100 text-yellow-800'
                                      }`}>
                                        {call.status}
                                      </span>
                                    </td>
                                    <td className="px-4 py-3 text-sm text-gray-600">{formatTimestamp(call.timestamp)}</td>
                                    <td className="px-4 py-3 text-sm text-gray-600">{call.retry_attempts}</td>
                                    <td className="px-4 py-3">
                                      <button
                                        onClick={() => toggleModelCallDetails(call.id)}
                                        className="text-blue-600 hover:text-blue-800 text-sm font-medium"
                                      >
                                        {expandedModelCalls.has(call.id) ? 'Hide' : 'Details'}
                                      </button>
                                    </td>
                                  </tr>
                                  {expandedModelCalls.has(call.id) && (
                                    <tr className="bg-gray-50">
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
                      <h3 className="font-semibold text-gray-900 mb-4 text-left">Transcript Segments ({stats.transcript_segments?.length || 0})</h3>
                      <div className="bg-white border rounded-lg overflow-hidden">
                        <div className="overflow-x-auto">
                          <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Seq #</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time Range</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Label</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Text</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                              {(stats.transcript_segments || []).map((segment) => (
                                <tr key={segment.id} className={`hover:bg-gray-50 ${
                                  segment.primary_label === 'ad' ? 'bg-red-50' : ''
                                }`}>
                                  <td className="px-4 py-3 text-sm text-gray-900">{segment.sequence_num}</td>
                                  <td className="px-4 py-3 text-sm text-gray-700">
                                    {formatTimeHMS(segment.start_time)} - {formatTimeHMS(segment.end_time)}
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                                      segment.primary_label === 'ad'
                                        ? 'bg-rose-100 text-rose-900'
                                        : 'bg-emerald-100 text-emerald-900'
                                    }`}>
                                      {segment.primary_label === 'ad' ? 'Ad' : 'Content'}
                                    </span>
                                  </td>
                                  <td className="px-4 py-3 text-sm text-gray-900 max-w-md">
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
                      <h3 className="font-semibold text-gray-900 mb-4 text-left">Identifications ({stats.identifications?.length || 0})</h3>
                      <div className="bg-white border rounded-lg overflow-hidden">
                        <div className="overflow-x-auto">
                          <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Segment ID</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time Range</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Label</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Confidence</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Model Call</th>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Text</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                              {(stats.identifications || []).map((identification) => (
                                <tr
                                  key={identification.id}
                                  className={`hover:bg-gray-50 ${
                                    identification.label === 'ad' ? 'bg-rose-50' : ''
                                  }`}
                                >
                                  <td className="px-4 py-3 text-sm text-gray-900">{identification.id}</td>
                                  <td className="px-4 py-3 text-sm text-gray-600">{identification.transcript_segment_id}</td>
                                  <td className="px-4 py-3 text-sm text-gray-700">
                                    {formatTimeHMS(identification.segment_start_time)} - {formatTimeHMS(identification.segment_end_time)}
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                                      identification.label === 'ad'
                                        ? 'bg-rose-100 text-rose-900'
                                        : 'bg-emerald-100 text-emerald-900'
                                    }`}>
                                      {identification.label}
                                    </span>
                                  </td>
                                  <td className="px-4 py-3 text-sm text-gray-600">
                                    {identification.confidence ? identification.confidence.toFixed(2) : 'N/A'}
                                  </td>
                                  <td className="px-4 py-3 text-sm text-gray-600">{identification.model_call_id}</td>
                                  <td className="px-4 py-3 text-sm text-gray-900 max-w-md">
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

                  {/* Settings Tab */}
                  {activeTab === 'settings' && (
                    <div className="space-y-6">
                      {/* Overall Stats Summary */}
                      {statsSummary && (
                        <div className="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-lg p-4">
                          <h3 className="font-semibold text-gray-900 mb-3 text-left">Overall Ad Removal Statistics</h3>
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                            <div className="text-center">
                              <div className="text-2xl font-bold text-indigo-600">{statsSummary.total_episodes_processed}</div>
                              <div className="text-sm text-gray-600">Episodes Processed</div>
                            </div>
                            <div className="text-center">
                              <div className="text-2xl font-bold text-purple-600">{statsSummary.total_ad_segments_removed}</div>
                              <div className="text-sm text-gray-600">Ads Removed</div>
                            </div>
                            <div className="text-center">
                              <div className="text-2xl font-bold text-green-600">{statsSummary.total_time_saved_formatted}</div>
                              <div className="text-sm text-gray-600">Time Saved</div>
                            </div>
                            <div className="text-center">
                              <div className="text-2xl font-bold text-orange-600">{statsSummary.average_percentage_removed.toFixed(1)}%</div>
                              <div className="text-sm text-gray-600">Avg Removed</div>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Preset Selection */}
                      <div>
                        <h3 className="font-semibold text-gray-900 mb-4 text-left">Ad Detection Aggressiveness</h3>
                        <p className="text-sm text-gray-600 mb-4 text-left">
                          Choose how aggressively the AI should detect and remove ads. More aggressive settings may occasionally remove non-ad content.
                        </p>
                        
                        {presetsLoading ? (
                          <div className="flex items-center justify-center py-8">
                            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600"></div>
                            <span className="ml-2 text-gray-600">Loading presets...</span>
                          </div>
                        ) : (
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            {(presets || []).map((preset: PromptPreset) => {
                              const isActive = preset.is_active || pendingPresetId === preset.id;

                              return (
                                <div
                                  key={preset.id}
                                  className={`relative border-2 rounded-lg p-4 cursor-pointer transition-all ${
                                    isActive
                                      ? 'border-purple-500 bg-purple-50'
                                      : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                                  }`}
                                  onClick={() => {
                                    if (!isActive && !activatePresetMutation.isPending) {
                                      setPendingPresetId(preset.id);
                                      activatePresetMutation.mutate(preset.id);
                                    }
                                  }}
                                >
                                  {isActive && (
                                    <div className="absolute top-2 right-2">
                                      <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-500 text-white">
                                        Active
                                      </span>
                                    </div>
                                  )}
                                  <h4 className="font-semibold text-gray-900 text-left">{preset.name}</h4>
                                  <p className="text-sm text-gray-600 mt-1 text-left">{preset.description}</p>
                                  <div className="mt-3 flex items-center gap-2">
                                    <span className={`inline-flex px-2 py-1 rounded-full text-xs font-medium ${
                                      preset.aggressiveness === 'conservative' ? 'bg-green-100 text-green-800' :
                                      preset.aggressiveness === 'balanced' ? 'bg-yellow-100 text-yellow-800' :
                                      preset.aggressiveness === 'aggressive' ? 'bg-orange-100 text-orange-800' :
                                      'bg-red-100 text-red-800'
                                    }`}>
                                      {preset.aggressiveness}
                                    </span>
                                    <span className="text-xs text-gray-500">
                                      Min confidence: {(preset.min_confidence * 100).toFixed(0)}%
                                    </span>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>

                      {/* Active Preset Info */}
                      {activePreset && (
                        <div className="bg-gray-50 rounded-lg p-4">
                          <h3 className="font-semibold text-gray-900 mb-2 text-left">Current Settings</h3>
                          <div className="text-sm text-gray-600 text-left">
                            <p><strong>Preset:</strong> {activePreset.name}</p>
                            <p><strong>Aggressiveness:</strong> {activePreset.aggressiveness}</p>
                            <p><strong>Minimum Confidence:</strong> {(activePreset.min_confidence * 100).toFixed(0)}%</p>
                            <p className="mt-2 text-xs text-gray-500">
                              Note: Changing the preset will affect future episode processing. Already processed episodes will not be affected unless reprocessed.
                            </p>
                          </div>
                        </div>
                      )}
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
