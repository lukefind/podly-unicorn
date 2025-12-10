import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { configApi, authApi } from '../services/api';
import { toast } from 'react-hot-toast';
import type {
  CombinedConfig,
  ConfigResponse,
  EnvOverrideEntry,
  EnvOverrideMap,
  LLMConfig,
  ManagedUser,
  WhisperConfig,
} from '../types';
import { useAuth } from '../contexts/AuthContext';
import AdminUserStats from '../components/AdminUserStats';

const ENV_FIELD_LABELS: Record<string, string> = {
  'groq.api_key': 'Groq API Key',
  'llm.llm_api_key': 'LLM API Key',
  'llm.llm_model': 'LLM Model',
  'llm.openai_base_url': 'LLM Base URL',
  'whisper.whisper_type': 'Whisper Mode',
  'whisper.api_key': 'Whisper API Key',
  'whisper.model': 'Whisper Model',
  'whisper.base_url': 'Whisper Base URL',
  'whisper.timeout_sec': 'Whisper Timeout (sec)',
  'whisper.chunksize_mb': 'Whisper Chunk Size (MB)',
  'whisper.max_retries': 'Whisper Max Retries',
};

const DEFAULT_ENV_HINTS: Record<string, EnvOverrideEntry> = {
  'groq.api_key': { env_var: 'GROQ_API_KEY' },
  'llm.llm_api_key': { env_var: 'LLM_API_KEY' },
  'llm.llm_model': { env_var: 'LLM_MODEL' },
  'llm.openai_base_url': { env_var: 'OPENAI_BASE_URL' },
  'whisper.whisper_type': { env_var: 'WHISPER_TYPE' },
  'whisper.api_key': { env_var: 'WHISPER_REMOTE_API_KEY' },
  'whisper.base_url': { env_var: 'WHISPER_REMOTE_BASE_URL' },
  'whisper.model': { env_var: 'WHISPER_REMOTE_MODEL' },
  'whisper.timeout_sec': { env_var: 'WHISPER_REMOTE_TIMEOUT_SEC' },
  'whisper.chunksize_mb': { env_var: 'WHISPER_REMOTE_CHUNKSIZE_MB' },
  'whisper.max_retries': { env_var: 'GROQ_MAX_RETRIES' },
};

const getValueAtPath = (obj: unknown, path: string): unknown => {
  if (!obj || typeof obj !== 'object') {
    return undefined;
  }
  return path.split('.').reduce<unknown>((acc, key) => {
    if (!acc || typeof acc !== 'object') {
      return undefined;
    }
    return (acc as Record<string, unknown>)[key];
  }, obj);
};

const valuesDiffer = (a: unknown, b: unknown): boolean => {
  if (a === b) {
    return false;
  }
  const aEmpty = a === null || a === undefined || a === '';
  const bEmpty = b === null || b === undefined || b === '';
  if (aEmpty && bEmpty) {
    return false;
  }
  return true;
};

export default function ConfigPage() {
  const { data, isLoading, refetch } = useQuery<ConfigResponse>({
    queryKey: ['config'],
    queryFn: configApi.getConfig,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const configData = data?.config;
  const envOverrides = useMemo<EnvOverrideMap>(() => data?.env_overrides ?? {}, [data]);
  const getEnvHint = useCallback(
    (path: string, fallback?: EnvOverrideEntry) => envOverrides[path] ?? fallback ?? DEFAULT_ENV_HINTS[path],
    [envOverrides],
  );

  const { changePassword, refreshUser, user, logout, requireAuth } = useAuth();

  const [passwordForm, setPasswordForm] = useState({ current: '', next: '', confirm: '' });
  const [passwordSubmitting, setPasswordSubmitting] = useState(false);

  const [newUser, setNewUser] = useState({ username: '', password: '', confirm: '', role: 'user' });
  const [activeResetUser, setActiveResetUser] = useState<string | null>(null);
  const [resetPassword, setResetPassword] = useState('');
  const [resetConfirm, setResetConfirm] = useState('');
  const [envWarningPaths, setEnvWarningPaths] = useState<string[]>([]);
  const [showEnvWarning, setShowEnvWarning] = useState(false);

  const showSecurityControls = requireAuth && !!user;

  const {
    data: managedUsers,
    isLoading: usersLoading,
    refetch: refetchUsers,
  } = useQuery<ManagedUser[]>({
    queryKey: ['auth-users'],
    queryFn: async () => {
      const response = await authApi.listUsers();
      return response.users;
    },
    enabled: showSecurityControls && user.role === 'admin',
  });

  const [pending, setPending] = useState<CombinedConfig | null>(null);
  const [hasEdits, setHasEdits] = useState(false);
  const [showGroqHelp, setShowGroqHelp] = useState(false);
  const [showGroqPricing, setShowGroqPricing] = useState(false);
  const [showBaseUrlInfo, setShowBaseUrlInfo] = useState(false);
  const [localWhisperAvailable, setLocalWhisperAvailable] = useState<boolean | null>(null);
  const [llmStatus, setLlmStatus] = useState<'loading' | 'ok' | 'error'>('loading');
  const [llmMessage, setLlmMessage] = useState<string>('');
  const [llmError, setLlmError] = useState<string>('');
  const [whisperStatus, setWhisperStatus] = useState<'loading' | 'ok' | 'error'>('loading');
  const [whisperMessage, setWhisperMessage] = useState<string>('');
  const [whisperError, setWhisperError] = useState<string>('');
  const initialProbeDone = useRef(false);
  const groqRecommendedModel = useMemo(() => 'groq/openai/gpt-oss-120b', []);
  const groqRecommendedWhisper = useMemo(() => 'whisper-large-v3-turbo', []);

  const getErrorMessage = (error: unknown, fallback = 'Request failed.') => {
    if (axios.isAxiosError(error)) {
      return error.response?.data?.error || error.response?.data?.message || error.message || fallback;
    }
    if (error instanceof Error) {
      return error.message;
    }
    return fallback;
  };

  const handlePasswordSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (passwordForm.next !== passwordForm.confirm) {
      toast.error('New passwords do not match.');
      return;
    }

    setPasswordSubmitting(true);
    try {
      await changePassword(passwordForm.current, passwordForm.next);
      toast.success('Password updated. Update PODLY_ADMIN_PASSWORD to match.');
      setPasswordForm({ current: '', next: '', confirm: '' });
      await refreshUser();
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to update password.'));
    } finally {
      setPasswordSubmitting(false);
    }
  };

  const handleCreateUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const username = newUser.username.trim();
    if (!username) {
      toast.error('Username is required.');
      return;
    }
    if (newUser.password !== newUser.confirm) {
      toast.error('Passwords do not match.');
      return;
    }

    try {
      await authApi.createUser({
        username,
        password: newUser.password,
        role: newUser.role,
      });
      toast.success(`User '${username}' created.`);
      setNewUser({ username: '', password: '', confirm: '', role: 'user' });
      await refetchUsers();
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to create user.'));
    }
  };

  const handleRoleChange = async (username: string, role: string) => {
    try {
      await authApi.updateUser(username, { role });
      toast.success(`Updated role for ${username}.`);
      await refetchUsers();
      if (user && user.username === username) {
        await refreshUser();
      }
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to update role.'));
    }
  };

  const handleResetPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!activeResetUser) {
      return;
    }
    if (resetPassword !== resetConfirm) {
      toast.error('Passwords do not match.');
      return;
    }

    try {
      await authApi.updateUser(activeResetUser, { password: resetPassword });
      toast.success(`Password updated for ${activeResetUser}.`);
      setActiveResetUser(null);
      setResetPassword('');
      setResetConfirm('');
      await refetchUsers();
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to update password.'));
    }
  };

  const handleDeleteUser = async (username: string) => {
    const confirmed = window.confirm(`Delete user '${username}'? This action cannot be undone.`);
    if (!confirmed) {
      return;
    }
    try {
      await authApi.deleteUser(username);
      toast.success(`Deleted user '${username}'.`);
      await refetchUsers();
      if (user && user.username === username) {
        logout();
      }
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to delete user.'));
    }
  };

  const getWhisperApiKey = (w: WhisperConfig | undefined): string => {
    if (!w) return '';
    if (w.whisper_type === 'remote') return w.api_key ?? '';
    if (w.whisper_type === 'groq') return w.api_key ?? '';
    return '';
  };

  const whisperApiKeyPreview =
    pending?.whisper?.whisper_type === 'remote' || pending?.whisper?.whisper_type === 'groq'
      ? pending.whisper.api_key_preview
      : undefined;

  const whisperApiKeyPlaceholder = useMemo(() => {
    if (pending?.whisper?.whisper_type === 'remote' || pending?.whisper?.whisper_type === 'groq') {
      if (whisperApiKeyPreview) {
        return whisperApiKeyPreview;
      }
      const override = envOverrides['whisper.api_key'];
      if (override) {
        return override.value_preview || override.value || '';
      }
    }
    return '';
  }, [whisperApiKeyPreview, pending?.whisper?.whisper_type, envOverrides]);

  const updatePending = useCallback(
    (
      transform: (prevConfig: CombinedConfig) => CombinedConfig,
      markDirty: boolean = true,
    ) => {
      let updated = false;
      setPending((prevConfig) => {
        if (!prevConfig) {
          return prevConfig;
        }
        const nextConfig = transform(prevConfig);
        if (nextConfig === prevConfig) {
          return prevConfig;
        }
        updated = true;
        return nextConfig;
      });

      if (updated && markDirty) {
        setHasEdits(true);
      }
    },
    [],
  );

  const setField = useCallback(
    (path: string[], value: unknown) => {
      updatePending((prevConfig) => {
        const prevRecord = prevConfig as unknown as Record<string, unknown>;
        const lastIndex = path.length - 1;

        let existingParent: Record<string, unknown> | null = prevRecord;
        for (let i = 0; i < lastIndex; i++) {
          const key = path[i];
          const rawNext: unknown = existingParent?.[key];
          const nextParent: Record<string, unknown> | null =
            rawNext && typeof rawNext === 'object'
              ? (rawNext as Record<string, unknown>)
              : null;
          if (!nextParent) {
            existingParent = null;
            break;
          }
          existingParent = nextParent;
        }

        if (existingParent) {
          const currentValue = existingParent[path[lastIndex]];
          if (Object.is(currentValue, value)) {
            return prevConfig;
          }
        }

        const next: Record<string, unknown> = { ...prevRecord };

        let cursor: Record<string, unknown> = next;
        let sourceCursor: Record<string, unknown> = prevRecord;

        for (let i = 0; i < lastIndex; i++) {
          const key = path[i];
          const currentSource =
            (sourceCursor?.[key] as Record<string, unknown>) ?? {};
          const clonedChild: Record<string, unknown> = { ...currentSource };
          cursor[key] = clonedChild;
          cursor = clonedChild;
          sourceCursor = currentSource;
        }

        cursor[path[lastIndex]] = value;

        return next as unknown as CombinedConfig;
      });
    },
    [updatePending],
  );

  useEffect(() => {
    if (!configData) {
      return;
    }
    setPending((prev) => {
      if (prev === null) {
        return configData;
      }
      if (hasEdits) {
        return prev;
      }
      return configData;
    });
  }, [configData, hasEdits]);

  const probeConnections = async () => {
    if (!pending) return;
    setLlmStatus('loading');
    setWhisperStatus('loading');
    setLlmMessage('');
    setLlmError('');
    setWhisperMessage('');
    setWhisperError('');
    try {
      const [llmRes, whisperRes] = await Promise.all([
        configApi.testLLM({ llm: pending.llm as LLMConfig }),
        configApi.testWhisper({ whisper: pending.whisper as WhisperConfig }),
      ]);

      if (llmRes?.ok) {
        setLlmStatus('ok');
        setLlmMessage(llmRes.message || 'LLM connection OK');
      } else {
        setLlmStatus('error');
        setLlmError(llmRes?.error || 'LLM connection failed');
      }

      if (whisperRes?.ok) {
        setWhisperStatus('ok');
        setWhisperMessage(whisperRes.message || 'Whisper connection OK');
      } else {
        setWhisperStatus('error');
        setWhisperError(whisperRes?.error || 'Whisper test failed');
      }
    } catch (err: unknown) {
      const e = err as { response?: { data?: { error?: string; message?: string } }; message?: string };
      const msg = e?.response?.data?.error || e?.response?.data?.message || e?.message || 'Connection test failed';
      // Only set error status if we haven't already set a success status
      if (llmStatus !== 'ok') {
        setLlmStatus('error');
        setLlmError(msg);
      }
      if (whisperStatus !== 'ok') {
        setWhisperStatus('error');
        setWhisperError(msg);
      }
    }
  };

  useEffect(() => {
    if (!pending || initialProbeDone.current) return;
    initialProbeDone.current = true;
    void probeConnections();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      return configApi.updateConfig((pending ?? {}) as Partial<CombinedConfig>);
    },
    onSuccess: () => {
      setHasEdits(false);
      refetch();
    },
  });

  const saveToastMessages = {
    loading: 'Saving changes...',
    success: 'Configuration saved',
    error: (err: unknown) => {
      if (typeof err === 'object' && err !== null) {
        const e = err as {
          response?: { data?: { error?: string; details?: string; message?: string } };
          message?: string;
        };
        return (
          e.response?.data?.message ||
          e.response?.data?.error ||
          e.response?.data?.details ||
          e.message ||
          'Failed to save configuration'
        );
      }
      return 'Failed to save configuration';
    },
  } as const;

  const getEnvManagedConflicts = (): string[] => {
    if (!pending || !configData) {
      return [];
    }
    return Object.keys(envOverrides).filter((path) => {
      const baseline = getValueAtPath(configData, path);
      const current = getValueAtPath(pending, path);
      return valuesDiffer(current, baseline);
    });
  };

  const triggerSaveMutation = () => {
    toast.promise(saveMutation.mutateAsync(), saveToastMessages);
  };

  const handleSave = () => {
    if (saveMutation.isPending) {
      return;
    }
    const envConflicts = getEnvManagedConflicts();
    if (envConflicts.length > 0) {
      setEnvWarningPaths(envConflicts);
      setShowEnvWarning(true);
      return;
    }
    triggerSaveMutation();
  };

  const handleConfirmEnvWarning = () => {
    setShowEnvWarning(false);
    triggerSaveMutation();
  };

  const handleDismissEnvWarning = () => {
    setShowEnvWarning(false);
    setEnvWarningPaths([]);
  };

  const renderSaveButton = () => (
    <div className="flex items-center justify-end">
      <button
        onClick={handleSave}
        className="px-3 py-2 text-sm rounded bg-gradient-to-r from-purple-600 to-pink-500 text-white hover:from-purple-700 hover:to-pink-600 disabled:opacity-60"
        disabled={saveMutation.isPending}
      >
        {saveMutation.isPending ? 'Saving...' : 'Save Changes'}
      </button>
    </div>
  );

  const applyGroqKeyMutation = useMutation({
    mutationFn: async (key: string) => {
      const next = {
        llm: {
          ...(pending?.llm as LLMConfig),
          llm_api_key: key,
          llm_model: groqRecommendedModel,
        },
        whisper: {
          whisper_type: 'groq',
          api_key: key,
          model: groqRecommendedWhisper,
          language: 'en',
          max_retries: 3,
        },
      } as Partial<CombinedConfig>;

      updatePending((prevConfig) => ({
        ...prevConfig,
        llm: next.llm as LLMConfig,
        whisper: next.whisper as WhisperConfig,
      }));

      const [llmRes, whisperRes] = await Promise.all([
        configApi.testLLM({ llm: next.llm as LLMConfig }),
        configApi.testWhisper({ whisper: next.whisper as WhisperConfig }),
      ]);
      if (!llmRes?.ok) throw new Error(llmRes?.error || 'LLM test failed');
      if (!whisperRes?.ok) throw new Error(whisperRes?.error || 'Whisper test failed');

      return await configApi.updateConfig(next);
    },
    onSuccess: () => {
      setHasEdits(false);
      refetch();
      toast.success('Groq key verified and saved. Defaults applied.');
      setLlmStatus('ok');
      setLlmMessage('LLM connection OK');
      setWhisperStatus('ok');
      setWhisperMessage('Whisper connection OK');
    },
  });

  // Probe whisper capabilities once and adapt UI/state
  useEffect(() => {
    let cancelled = false;
    configApi
      .getWhisperCapabilities()
      .then((res) => {
        if (!cancelled) setLocalWhisperAvailable(!!res.local_available);
      })
      .catch(() => {
        if (!cancelled) setLocalWhisperAvailable(false);
      });
    return () => {
        cancelled = true;
    };
  }, []);

  // If local is unavailable but selected, switch to a safe default
  useEffect(() => {
    if (!pending || localWhisperAvailable !== false) return;
    const currentType = pending.whisper.whisper_type;
    if (currentType === 'local') {
      setField(['whisper', 'whisper_type'], 'remote');
    }
  }, [localWhisperAvailable, pending]);

  if (isLoading || !pending) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex flex-col items-center gap-3">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
          <p className="text-sm text-gray-500">Loading configuration...</p>
        </div>
      </div>
    );
  }

  const handleWhisperTypeChange = (
    nextType: 'local' | 'remote' | 'groq'
  ) => {
    updatePending((prevConfig) => {
      const prevWhisper = {
        ...(prevConfig.whisper as unknown as Record<string, unknown>),
      };
      const prevModelRaw = (prevWhisper?.model as string | undefined) ?? '';
      const prevModel = String(prevModelRaw).toLowerCase();

      const isNonGroqDefault = prevModel === 'base' || prevModel === 'base.en' || prevModel === 'whisper-1';
      const isDeprecatedGroq = prevModel === 'distil-whisper-large-v3-en';

      let nextModel: string | undefined = prevWhisper?.model as string | undefined;

      if (nextType === 'groq') {
        if (!nextModel || isNonGroqDefault || isDeprecatedGroq) {
          nextModel = 'whisper-large-v3-turbo';
        }
      } else if (nextType === 'remote') {
        if (!nextModel || prevModel === 'base' || prevModel === 'base.en') {
          nextModel = 'whisper-1';
        }
      } else if (nextType === 'local') {
        if (!nextModel || prevModel === 'whisper-1' || prevModel.startsWith('whisper-large')) {
          nextModel = 'base.en';
        }
      }

      const nextWhisper: Record<string, unknown> = {
        ...prevWhisper,
        whisper_type: nextType,
      };

      if (nextType === 'groq') {
        nextWhisper.model = nextModel ?? 'whisper-large-v3-turbo';
        nextWhisper.language = (prevWhisper.language as string | undefined) || 'en';
        delete nextWhisper.base_url;
        delete nextWhisper.timeout_sec;
        delete nextWhisper.chunksize_mb;
      } else if (nextType === 'remote') {
        nextWhisper.model = nextModel ?? 'whisper-1';
        nextWhisper.language = (prevWhisper.language as string | undefined) || 'en';
      } else if (nextType === 'local') {
        nextWhisper.model = nextModel ?? 'base.en';
        delete nextWhisper.api_key;
      } else if (nextType === 'test') {
        delete nextWhisper.model;
        delete nextWhisper.api_key;
      }

      return {
        ...prevConfig,
        whisper: nextWhisper as unknown as WhisperConfig,
      } as CombinedConfig;
    });
  };


  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold rainbow-text">Settings ⚙️</h1>
          <p className="text-purple-600 mt-1">Configure your LLM and Whisper connections</p>
        </div>
        {hasEdits && (
          <div className="flex items-center gap-3">
            <span className="text-sm text-pink-600">✨ Unsaved changes</span>
            <button
              onClick={() => {
                setPending(configData ?? null);
                setHasEdits(false);
              }}
              className="px-4 py-2 text-sm font-medium text-purple-700 bg-white/80 border border-purple-200 rounded-xl hover:bg-purple-50 transition-colors"
            >
              Discard
            </button>
            <button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              className="px-4 py-2 text-sm font-medium text-white bg-gradient-to-r from-pink-500 via-purple-500 to-cyan-500 rounded-xl hover:shadow-lg hover:shadow-purple-500/30 transition-all disabled:opacity-50"
            >
              {saveMutation.isPending ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        )}
      </div>

      <Section title="Connection Status">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className={`flex items-center justify-between rounded-lg p-4 ${
            llmStatus === 'ok' ? 'bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-700' :
            llmStatus === 'error' ? 'bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700' :
            'bg-purple-50 dark:bg-purple-900/30 border border-purple-200 dark:border-purple-700'
          }`}>
            <div className="flex items-center gap-3">
              <div className={`w-3 h-3 rounded-full ${
                llmStatus === 'ok' ? 'bg-green-500' :
                llmStatus === 'error' ? 'bg-red-500' :
                'bg-purple-400 animate-pulse'
              }`} />
              <div>
                <div className="text-sm font-medium text-gray-900 dark:text-purple-100">LLM Connection</div>
                <div className={`text-xs ${
                  llmStatus === 'ok' ? 'text-green-700 dark:text-green-300' :
                  llmStatus === 'error' ? 'text-red-700 dark:text-red-300' :
                  'text-gray-600 dark:text-purple-300'
                }`}>
                  {llmStatus === 'loading' && 'Testing connection...'}
                  {llmStatus === 'ok' && (llmMessage || 'Connected')}
                  {llmStatus === 'error' && (llmError || 'Connection failed')}
                </div>
              </div>
            </div>
            <button
              type="button"
              className="px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-purple-200 bg-white dark:bg-purple-800 border border-gray-300 dark:border-purple-600 rounded-lg hover:bg-gray-50 dark:hover:bg-purple-700 transition-colors"
              onClick={() => void probeConnections()}
            >
              Test
            </button>
          </div>
          <div className={`flex items-center justify-between rounded-lg p-4 ${
            whisperStatus === 'ok' ? 'bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-700' :
            whisperStatus === 'error' ? 'bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700' :
            'bg-purple-50 dark:bg-purple-900/30 border border-purple-200 dark:border-purple-700'
          }`}>
            <div className="flex items-center gap-3">
              <div className={`w-3 h-3 rounded-full ${
                whisperStatus === 'ok' ? 'bg-green-500' :
                whisperStatus === 'error' ? 'bg-red-500' :
                'bg-purple-400 animate-pulse'
              }`} />
              <div>
                <div className="text-sm font-medium text-gray-900 dark:text-purple-100">Whisper Connection</div>
                <div className={`text-xs ${
                  whisperStatus === 'ok' ? 'text-green-700 dark:text-green-300' :
                  whisperStatus === 'error' ? 'text-red-700 dark:text-red-300' :
                  'text-gray-600 dark:text-purple-300'
                }`}>
                  {whisperStatus === 'loading' && 'Testing connection...'}
                  {whisperStatus === 'ok' && (whisperMessage || 'Connected')}
                  {whisperStatus === 'error' && (whisperError || 'Connection failed')}
                </div>
              </div>
            </div>
            <button
              type="button"
              className="px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-purple-200 bg-white dark:bg-purple-800 border border-gray-300 dark:border-purple-600 rounded-lg hover:bg-gray-50 dark:hover:bg-purple-700 transition-colors"
              onClick={() => void probeConnections()}
            >
              Test
            </button>
          </div>
        </div>
      </Section>

      <Section title="Quick Setup">
        <div className="text-sm text-gray-700 dark:text-purple-200 mb-2 flex items-center gap-2">
          <span>Enter your Groq API key for a fast, cheaper setup. For better ad detection accuracy, use xAI Grok instead (see Advanced Settings).</span>
          <button
            type="button"
            className="text-indigo-600 dark:text-indigo-400 hover:underline"
            onClick={() => setShowGroqHelp((v) => !v)}
          >
            {showGroqHelp ? 'Hide help' : '(need help getting a key?)'}
          </button>
          <button
            type="button"
            className="text-indigo-600 dark:text-indigo-400 hover:underline"
            onClick={() => setShowGroqPricing((v) => !v)}
          >
            {showGroqPricing ? 'Hide pricing' : '(pricing guide)'}
          </button>
        </div>
        
        {/* Groq vs Grok warning */}
        <div className="mb-3 p-3 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-700 rounded-lg">
          <div className="flex items-start gap-2">
            <span className="text-amber-500 text-lg">⚠️</span>
            <div className="text-sm text-amber-800 dark:text-amber-200">
              <strong>Groq ≠ Grok!</strong> These are different companies:
              <ul className="mt-1 ml-4 list-disc text-xs">
                <li><strong>Groq</strong> (groq.com) - Fast inference platform. Key starts with <code className="bg-amber-100 dark:bg-amber-800 px-1 rounded">gsk_</code></li>
                <li><strong>Grok</strong> (xAI) - Different LLM provider. Key starts with <code className="bg-amber-100 dark:bg-amber-800 px-1 rounded">xai-</code></li>
              </ul>
            </div>
          </div>
        </div>
        {showGroqHelp && (
          <div className="text-sm text-gray-700 mb-2 bg-indigo-50 border border-indigo-200 rounded p-3 space-y-2">
            <ol className="list-decimal pl-5 space-y-1">
              <li>
                Visit the{' '}
                <a
                  className="text-indigo-700 underline"
                  href="https://console.groq.com/keys"
                  target="_blank"
                  rel="noreferrer"
                >
                  Groq Console
                </a>{' '}
                and sign in or create an account.
              </li>
              <li>Open the Keys page and click "Create API Key".</li>
              <li>Copy the key (it starts with <code>gsk_</code>) and paste it below.</li>
              <li>
                <strong>Recommended:</strong> Set a billing limit at{' '}
                <a
                  className="text-indigo-700 underline"
                  href="https://console.groq.com/settings/billing"
                  target="_blank"
                  rel="noreferrer"
                >
                  Settings → Billing → Limits
                </a>{' '}
                to control costs and receive usage alerts.
              </li>
            </ol>
          </div>
        )}
        {showGroqPricing && (
          <div className="text-sm text-gray-700 mb-2 bg-green-50 border border-green-200 rounded p-3 space-y-3">
            <div>
              <h4 className="font-semibold text-green-800 mb-2">Groq Pricing Guide</h4>
              <p className="text-green-700 mb-3">
                Based on the recommended models: <code>whisper-large-v3-turbo</code> and <code>llama-3.3-70b-versatile</code>
              </p>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="bg-white border border-green-300 rounded p-3">
                <h5 className="font-medium text-green-800 mb-2">Whisper (Transcription)</h5>
                <ul className="space-y-1 text-green-700">
                  <li>• <strong>whisper-large-v3-turbo:</strong> $0.04/hour</li>
                  <li>• Speed: 216x real-time</li>
                  <li>• Minimum charge: 10 seconds per request</li>
                </ul>
              </div>
              
              <div className="bg-white border border-green-300 rounded p-3">
                <h5 className="font-medium text-green-800 mb-2">LLM (Ad Detection)</h5>
                <ul className="space-y-1 text-green-700">
                  <li>• <strong>llama-3.3-70b-versatile:</strong></li>
                  <li>• Input: $0.59/1M tokens</li>
                  <li>• Output: $0.79/1M tokens</li>
                  <li>• ~1M tokens ≈ 750,000 words</li>
                </ul>
              </div>
            </div>
            
            <div className="bg-white border border-green-300 rounded p-3">
              <h5 className="font-medium text-green-800 mb-2">Estimated Monthly Cost (6 podcasts, 6 hours/week)</h5>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-green-700">
                <div>
                  <strong>Transcription:</strong><br />
                  24 hours/month × $0.04 = <span className="font-semibold">$0.96/month</span>
                </div>
                <div>
                  <strong>Ad Detection:</strong><br />
                  ~2M tokens × $0.69 avg = <span className="font-semibold">$1.38/month</span>
                </div>
                <div className="md:col-span-1">
                  <strong>Total Estimate:</strong><br />
                  <span className="font-semibold text-lg">~$2.34/month</span>
                </div>
              </div>
              <p className="text-xs text-green-600 mt-2">
                * Actual costs may vary based on podcast length, complexity, and token usage. 
                Consider setting a $5-10/month billing limit for safety.
              </p>
            </div>
          </div>
        )}
        <Field label="Groq API Key" envMeta={getEnvHint('groq.api_key')}>
          <div className="flex gap-2">
            <input
              className="input"
              type="text"
              placeholder={
                pending?.whisper?.whisper_type === 'groq'
                  ? pending?.whisper?.api_key_preview || ''
                  : pending?.llm?.llm_api_key_preview || ''
              }
              value={pending?.whisper?.whisper_type === 'groq' ? getWhisperApiKey(pending?.whisper) : (pending?.llm?.llm_api_key || '')}
              onChange={(e) => {
                const val = e.target.value;
                updatePending((prevConfig) => {
                  return {
                    ...prevConfig,
                    llm: {
                      ...(prevConfig.llm as LLMConfig),
                      llm_api_key: val,
                      llm_model: groqRecommendedModel,
                    },
                    whisper: {
                      whisper_type: 'groq',
                      api_key: val,
                      model: groqRecommendedWhisper,
                      language: 'en',
                      max_retries: 3,
                    } as WhisperConfig,
                  } as CombinedConfig;
                });
              }}
              onBlur={(e) => {
                const key = e.target.value.trim();
                if (!key) return;
                toast.promise(applyGroqKeyMutation.mutateAsync(key), {
                  loading: 'Verifying Groq key and applying defaults...',
                  success: 'Groq configured successfully',
                  error: (err: unknown) => {
                    const e = err as { response?: { data?: { error?: string; message?: string } }; message?: string };
                    return e?.response?.data?.error || e?.response?.data?.message || e?.message || 'Failed to configure Groq';
                  },
                });
              }}
              onPaste={(e) => {
                const text = e.clipboardData.getData('text').trim();
                if (!text) return;
                toast.promise(applyGroqKeyMutation.mutateAsync(text), {
                  loading: 'Verifying Groq key and applying defaults...',
                  success: 'Groq configured successfully',
                  error: (err: unknown) => {
                    const er = err as { response?: { data?: { error?: string; message?: string } }; message?: string };
                    return er?.response?.data?.error || er?.response?.data?.message || er?.message || 'Failed to configure Groq';
                  },
                });
              }}
            />
          </div>
        </Field>
      </Section>

      {showSecurityControls && (
                  <Section title="Account Security">
            <form className="grid gap-3 max-w-md" onSubmit={handlePasswordSubmit}>
              <Field label="Current password">
                <input
                  className="input"
                  type="password"
                  autoComplete="current-password"
                  value={passwordForm.current}
                  onChange={(event) => setPasswordForm((prev) => ({ ...prev, current: event.target.value }))}
                  required
                />
              </Field>
              <Field label="New password">
                <input
                  className="input"
                  type="password"
                  autoComplete="new-password"
                  value={passwordForm.next}
                  onChange={(event) => setPasswordForm((prev) => ({ ...prev, next: event.target.value }))}
                  required
                />
              </Field>
              <Field label="Confirm new password">
                <input
                  className="input"
                  type="password"
                  autoComplete="new-password"
                  value={passwordForm.confirm}
                  onChange={(event) => setPasswordForm((prev) => ({ ...prev, confirm: event.target.value }))}
                  required
                />
              </Field>
              <div className="flex flex-col gap-2 pt-2">
                <button
                  type="submit"
                  className="w-fit px-6 py-2.5 rounded-lg bg-gradient-to-r from-purple-600 to-pink-500 text-white text-sm font-medium hover:from-purple-700 hover:to-pink-600 disabled:opacity-60 shadow-sm"
                  disabled={passwordSubmitting}
                >
                  {passwordSubmitting ? 'Updating…' : 'Update password'}
                </button>
                <p className="text-xs text-purple-500">
                  After updating, rotate <code className="font-mono bg-purple-50 px-1 rounded">PODLY_ADMIN_PASSWORD</code> to match.
                </p>
              </div>
            </form>
          </Section>
      )}
      {showSecurityControls && user?.role === 'admin' && (
        <Section title="User Management">
          <div className="space-y-4">
            <form className="grid gap-3 md:grid-cols-2" onSubmit={handleCreateUser}>
              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input
                  className="input"
                  type="text"
                  value={newUser.username}
                  onChange={(event) => setNewUser((prev) => ({ ...prev, username: event.target.value }))}
                  placeholder="new_user"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input
                  className="input"
                  type="password"
                  value={newUser.password}
                  onChange={(event) => setNewUser((prev) => ({ ...prev, password: event.target.value }))}
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Confirm password</label>
                <input
                  className="input"
                  type="password"
                  value={newUser.confirm}
                  onChange={(event) => setNewUser((prev) => ({ ...prev, confirm: event.target.value }))}
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
                <select
                  className="input"
                  value={newUser.role}
                  onChange={(event) => setNewUser((prev) => ({ ...prev, role: event.target.value }))}
                >
                  <option value="user">user</option>
                  <option value="admin">admin</option>
                </select>
              </div>
              <div className="md:col-span-2 flex items-center justify-start">
                <button
                  type="submit"
                  className="px-4 py-2 rounded bg-gradient-to-r from-purple-600 to-pink-500 text-white text-sm font-medium hover:from-purple-700 hover:to-pink-600"
                >
                  Add user
                </button>
              </div>
            </form>

            <div className="space-y-3">
              {usersLoading && <div className="text-sm text-gray-600">Loading users…</div>}
              {!usersLoading && (!managedUsers || managedUsers.length === 0) && (
                <div className="text-sm text-gray-600">No additional users configured.</div>
              )}
              {!usersLoading && managedUsers && managedUsers.length > 0 && (
                <div className="space-y-3">
                  {managedUsers.map((managed) => {
                    const adminCount = managedUsers.filter((u) => u.role === 'admin').length;
                    const disableDemotion = managed.role === 'admin' && adminCount <= 1;
                    const disableDelete = disableDemotion;
                    const isActive = activeResetUser === managed.username;

                    return (
                      <div key={managed.id} className="border border-gray-200 rounded-lg p-3 space-y-3 bg-white">
                        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                          <div>
                            <div className="text-sm font-semibold text-gray-900">{managed.username}</div>
                            <div className="text-xs text-gray-500">
                              Added {new Date(managed.created_at).toLocaleString()} • Role {managed.role}
                            </div>
                          </div>
                          <div className="flex flex-wrap items-center gap-2">
                            <select
                              className="input text-sm"
                              value={managed.role}
                              onChange={(event) => {
                                const nextRole = event.target.value;
                                if (nextRole !== managed.role) {
                                  void handleRoleChange(managed.username, nextRole);
                                }
                              }}
                              disabled={disableDemotion && managed.role === 'admin'}
                            >
                              <option value="user">user</option>
                              <option value="admin">admin</option>
                            </select>
                            <button
                              type="button"
                              className="px-3 py-1 border border-gray-300 rounded-md text-sm hover:bg-gray-50"
                              onClick={() => {
                                if (isActive) {
                                  setActiveResetUser(null);
                                  setResetPassword('');
                                  setResetConfirm('');
                                } else {
                                  setActiveResetUser(managed.username);
                                  setResetPassword('');
                                  setResetConfirm('');
                                }
                              }}
                            >
                              {isActive ? 'Cancel' : 'Set password'}
                            </button>
                            <button
                              type="button"
                              className="px-3 py-1 border border-red-300 text-red-600 rounded-md text-sm hover:bg-red-50 disabled:opacity-50"
                              onClick={() => void handleDeleteUser(managed.username)}
                              disabled={disableDelete}
                            >
                              Delete
                            </button>
                          </div>
                        </div>

                        {isActive && (
                          <form className="grid gap-2 md:grid-cols-3" onSubmit={handleResetPassword}>
                            <div className="md:col-span-1">
                              <label className="block text-xs font-medium text-gray-600 mb-1">New password</label>
                              <input
                                className="input"
                                type="password"
                                value={resetPassword}
                                onChange={(event) => setResetPassword(event.target.value)}
                                required
                              />
                            </div>
                            <div className="md:col-span-1">
                              <label className="block text-xs font-medium text-gray-600 mb-1">Confirm password</label>
                              <input
                                className="input"
                                type="password"
                                value={resetConfirm}
                                onChange={(event) => setResetConfirm(event.target.value)}
                                required
                              />
                            </div>
                            <div className="md:col-span-1 flex items-end gap-2">
                              <button
                                type="submit"
                                className="px-4 py-2 rounded bg-gradient-to-r from-purple-600 to-pink-500 text-white text-sm hover:from-purple-700 hover:to-pink-600"
                              >
                                Update
                              </button>
                              <p className="text-xs text-gray-500">Share new credentials securely.</p>
                            </div>
                          </form>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </Section>
      )}

      {/* User Statistics - Admin only */}
      {showSecurityControls && user?.role === 'admin' && (
        <Section title="User Statistics">
          <AdminUserStats />
        </Section>
      )}

      {/* Advanced Settings - Always visible */}
      <div className="space-y-6">
        <div className="border-t border-purple-200 pt-6">
          <div className="flex items-center gap-3 mb-4">
            <h2 className="text-lg font-semibold text-gray-900">Advanced Settings</h2>
            <span className="text-xs px-2 py-1 rounded-full bg-amber-100 text-amber-700 font-medium">Changes below require clicking "Save Changes" to apply</span>
          </div>
        </div>
        <Section title="LLM Configuration">
            <Field label="API Key" envMeta={getEnvHint('llm.llm_api_key')}>
              <input
                className="input"
                type="text"
                placeholder={pending?.llm?.llm_api_key_preview || ''}
                value={pending?.llm?.llm_api_key || ''}
                onChange={(e) => setField(['llm', 'llm_api_key'], e.target.value)}
              />
            </Field>
            <label className="flex items-start justify-between gap-3">
              <div className="w-60">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-gray-700">OpenAI Base URL</span>
                  <button
                    type="button"
                    className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50"
                    onClick={() => setShowBaseUrlInfo((v) => !v)}
                    title="When is this used?"
                  >
                    ⓘ
                  </button>
                </div>
                <EnvVarHint meta={getEnvHint('llm.openai_base_url')} />
              </div>
              <div className="flex-1">
                <input
                  className="input"
                  type="text"
                  placeholder="https://api.openai.com/v1"
                  value={pending?.llm?.openai_base_url || ''}
                  onChange={(e) => setField(['llm', 'openai_base_url'], e.target.value)}
                />
                {showBaseUrlInfo && (
                  <div className="mt-2 text-xs bg-blue-50 border border-blue-200 rounded p-3 space-y-2">
                    <p className="font-medium text-blue-800">How model routing works:</p>
                    <div className="text-blue-700 space-y-1">
                      <p>• Models with a prefix like <code className="bg-white px-1 rounded">groq/</code> or <code className="bg-white px-1 rounded">anthropic/</code> are routed automatically by LiteLLM — the Base URL is ignored.</p>
                      <p>• Models <strong>without</strong> a prefix (e.g., <code className="bg-white px-1 rounded">gpt-4o</code>) use the Base URL you set here.</p>
                    </div>
                    <p className="text-blue-600 italic">If you're using Groq with a <code>groq/</code> prefix, you can leave Base URL empty.</p>
                  </div>
                )}
              </div>
              <style>{`.input{width:100%;padding:0.5rem;border:1px solid #e5e7eb;border-radius:0.375rem;font-size:0.875rem}`}</style>
            </label>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="Model" envMeta={getEnvHint('llm.llm_model')}>
                <div className="relative">
                  <input
                    list="llm-model-datalist"
                    className="input"
                    type="text"
                    value={pending?.llm?.llm_model ?? ''}
                    onChange={(e) => setField(['llm', 'llm_model'], e.target.value)}
                    placeholder="e.g. groq/openai/gpt-oss-120b"
                  />
                </div>
              </Field>
              <Field label="OpenAI Timeout (sec)">
                <input
                  className="input"
                  type="number"
                  value={pending?.llm?.openai_timeout ?? 300}
                  onChange={(e) => setField(['llm', 'openai_timeout'], Number(e.target.value))}
                />
              </Field>
              <Field label="OpenAI Max Tokens">
                <input
                  className="input"
                  type="number"
                  value={pending?.llm?.openai_max_tokens ?? 4096}
                  onChange={(e) => setField(['llm', 'openai_max_tokens'], Number(e.target.value))}
                />
              </Field>
              <Field label="Max Concurrent LLM Calls">
                <input
                  className="input"
                  type="number"
                  value={pending?.llm?.llm_max_concurrent_calls ?? 3}
                  onChange={(e) => setField(['llm', 'llm_max_concurrent_calls'], Number(e.target.value))}
                />
              </Field>
              <Field label="Max Retry Attempts">
                <input
                  className="input"
                  type="number"
                  value={pending?.llm?.llm_max_retry_attempts ?? 5}
                  onChange={(e) => setField(['llm', 'llm_max_retry_attempts'], Number(e.target.value))}
                />
              </Field>
              <Field label="Enable Token Rate Limiting">
                <input
                  type="checkbox"
                  checked={!!pending?.llm?.llm_enable_token_rate_limiting}
                  onChange={(e) => setField(['llm', 'llm_enable_token_rate_limiting'], e.target.checked)}
                />
              </Field>
              <Field label="Max Input Tokens Per Call (optional)">
                <input
                  className="input"
                  type="number"
                  value={pending?.llm?.llm_max_input_tokens_per_call ?? ''}
                  onChange={(e) => setField(['llm', 'llm_max_input_tokens_per_call'], e.target.value === '' ? null : Number(e.target.value))}
                />
              </Field>
              <Field label="Max Input Tokens Per Minute (optional)">
                <input
                  className="input"
                  type="number"
                  value={pending?.llm?.llm_max_input_tokens_per_minute ?? ''}
                  onChange={(e) => setField(['llm', 'llm_max_input_tokens_per_minute'], e.target.value === '' ? null : Number(e.target.value))}
                />
              </Field>
            </div>
            <div className="flex justify-center">
              <button
                onClick={() => {
                  toast.promise(
                    configApi.testLLM({ llm: pending.llm as LLMConfig }),
                    {
                      loading: 'Testing LLM connection...',
                      success: (res: { ok: boolean; message?: string }) => res?.message || 'LLM connection OK',
                      error: (err: unknown) => {
                        const e = err as { response?: { data?: { error?: string; message?: string } }; message?: string };
                        return (
                          e?.response?.data?.error ||
                          e?.response?.data?.message ||
                          e?.message ||
                          'LLM connection failed'
                        );
                      }
                    }
                  );
                }}
                className="mt-2 px-3 py-2 text-sm rounded bg-gradient-to-r from-purple-600 to-pink-500 text-white hover:from-purple-700 hover:to-pink-600"
              >
                Test LLM
              </button>
            </div>
          </Section>

          <Section title="Whisper">
            <Field label="Type" envMeta={getEnvHint('whisper.whisper_type')}>
              <select
                className="input"
                value={
                  (pending?.whisper?.whisper_type as string | undefined) ?? (localWhisperAvailable === false ? 'remote' : 'local')
                }
                onChange={(e) => handleWhisperTypeChange(e.target.value as 'local' | 'remote' | 'groq')}
              >
                {localWhisperAvailable !== false && <option value="local">local</option>}
                <option value="remote">remote</option>
                <option value="groq">groq</option>
              </select>
            </Field>
            {pending?.whisper?.whisper_type === 'local' && (
              <Field label="Local Model" envMeta={getEnvHint('whisper.model', { env_var: 'WHISPER_LOCAL_MODEL' })}>
                <input
                  className="input"
                  type="text"
                  value={pending?.whisper?.model || 'base'}
                  onChange={(e) => setField(['whisper', 'model'], e.target.value)}
                />
              </Field>
            )}
            {pending?.whisper?.whisper_type === 'remote' && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="API Key" envMeta={getEnvHint('whisper.api_key', { env_var: 'WHISPER_REMOTE_API_KEY' })}>
                  <input
                    className="input"
                    type="text"
                    placeholder={whisperApiKeyPlaceholder}
                    value={getWhisperApiKey(pending?.whisper)}
                    onChange={(e) => setField(['whisper', 'api_key'], e.target.value)}
                  />
                </Field>
                <Field label="Remote Model" envMeta={getEnvHint('whisper.model', { env_var: 'WHISPER_REMOTE_MODEL' })}>
                  <input
                    className="input"
                    type="text"
                    value={pending?.whisper?.model || 'whisper-1'}
                    onChange={(e) => setField(['whisper', 'model'], e.target.value)}
                  />
                </Field>
                <Field label="Base URL" envMeta={getEnvHint('whisper.base_url')}>
                  <input
                    className="input"
                    type="text"
                    placeholder="https://api.openai.com/v1"
                    value={pending?.whisper?.base_url || ''}
                    onChange={(e) => setField(['whisper', 'base_url'], e.target.value)}
                  />
                </Field>
                <Field label="Language">
                  <input
                    className="input"
                    type="text"
                    value={pending?.whisper?.language || 'en'}
                    onChange={(e) => setField(['whisper', 'language'], e.target.value)}
                  />
                </Field>
                <Field label="Timeout (sec)" envMeta={getEnvHint('whisper.timeout_sec')}>
                  <input
                    className="input"
                    type="number"
                    value={pending?.whisper?.timeout_sec ?? 600}
                    onChange={(e) => setField(['whisper', 'timeout_sec'], Number(e.target.value))}
                  />
                </Field>
                <Field label="Chunk Size (MB)" envMeta={getEnvHint('whisper.chunksize_mb')}>
                  <input
                    className="input"
                    type="number"
                    value={pending?.whisper?.chunksize_mb ?? 24}
                    onChange={(e) => setField(['whisper', 'chunksize_mb'], Number(e.target.value))}
                  />
                </Field>
              </div>
            )}
            {pending?.whisper?.whisper_type === 'groq' && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="API Key" envMeta={getEnvHint('whisper.api_key', { env_var: 'GROQ_API_KEY' })}>
                  <input
                    className="input"
                    type="text"
                    placeholder={whisperApiKeyPlaceholder}
                    value={getWhisperApiKey(pending?.whisper)}
                    onChange={(e) => setField(['whisper', 'api_key'], e.target.value)}
                  />
                </Field>
                <Field label="Model" envMeta={getEnvHint('whisper.model', { env_var: 'GROQ_WHISPER_MODEL' })}>
                  <input
                    className="input"
                    type="text"
                    value={pending?.whisper?.model || 'whisper-large-v3-turbo'}
                    onChange={(e) => setField(['whisper', 'model'], e.target.value)}
                  />
                </Field>
                <Field label="Language">
                  <input
                    className="input"
                    type="text"
                    value={pending?.whisper?.language || 'en'}
                    onChange={(e) => setField(['whisper', 'language'], e.target.value)}
                  />
                </Field>
                <Field label="Max Retries" envMeta={getEnvHint('whisper.max_retries')}>
                  <input
                    className="input"
                    type="number"
                    value={pending?.whisper?.max_retries ?? 3}
                    onChange={(e) => setField(['whisper', 'max_retries'], Number(e.target.value))}
                  />
                </Field>
              </div>
            )}
            <div className="flex justify-center">
              <button
                onClick={() => {
                  toast.promise(
                    configApi.testWhisper({ whisper: pending.whisper as WhisperConfig }),
                    {
                      loading: 'Testing Whisper...',
                      success: (res: { ok: boolean; message?: string }) => res?.message || 'Whisper OK',
                      error: (err: unknown) => {
                        const e = err as { response?: { data?: { error?: string; message?: string } }; message?: string };
                        return (
                          e?.response?.data?.error ||
                          e?.response?.data?.message ||
                          e?.message ||
                          'Whisper test failed'
                        );
                      }
                    }
                  );
                }}
                className="mt-2 px-3 py-2 text-sm rounded bg-gradient-to-r from-purple-600 to-pink-500 text-white hover:from-purple-700 hover:to-pink-600"
              >
                Test Whisper
              </button>
            </div>
          </Section>

          <Section title="Processing">
            <Field label="Number of Segments per Prompt">
              <input
                className="input"
                type="number"
                value={pending?.processing?.num_segments_to_input_to_prompt ?? 30}
                onChange={(e) => setField(['processing', 'num_segments_to_input_to_prompt'], Number(e.target.value))}
              />
            </Field>
          </Section>

          <Section title="Output">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="Fade (ms)">
                <input
                  className="input"
                  type="number"
                  value={pending?.output?.fade_ms ?? 3000}
                  onChange={(e) => setField(['output', 'fade_ms'], Number(e.target.value))}
                />
              </Field>
              <Field label="Min Segment Separation (sec)">
                <input
                  className="input"
                  type="number"
                  value={pending?.output?.min_ad_segement_separation_seconds ?? 60}
                  onChange={(e) => setField(['output', 'min_ad_segement_separation_seconds'], Number(e.target.value))}
                />
              </Field>
              <Field label="Min Segment Length (sec)">
                <input
                  className="input"
                  type="number"
                  value={pending?.output?.min_ad_segment_length_seconds ?? 14}
                  onChange={(e) => setField(['output', 'min_ad_segment_length_seconds'], Number(e.target.value))}
                />
              </Field>
              <Field label="Min Confidence">
                <input
                  className="input"
                  type="number"
                  step="0.01"
                  value={pending?.output?.min_confidence ?? 0.8}
                  onChange={(e) => setField(['output', 'min_confidence'], Number(e.target.value))}
                />
              </Field>
            </div>
          </Section>

          <Section title="App">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Field label="Feed Refresh Background Interval (min)">
                <input
                  className="input"
                  type="number"
                  value={pending?.app?.background_update_interval_minute ?? ''}
                  onChange={(e) => setField(['app', 'background_update_interval_minute'], e.target.value === '' ? null : Number(e.target.value))}
                />
              </Field>
              <Field label="Cleanup Retention (days)">
                <input
                  className="input"
                  type="number"
                  min={0}
                  value={pending?.app?.post_cleanup_retention_days ?? ''}
                  onChange={(e) => setField(['app', 'post_cleanup_retention_days'], e.target.value === '' ? null : Number(e.target.value))}
                />
              </Field>
              <Field label="Auto-whitelist new episodes">
                <input
                  type="checkbox"
                  checked={!!pending?.app?.automatically_whitelist_new_episodes}
                  onChange={(e) => setField(['app', 'automatically_whitelist_new_episodes'], e.target.checked)}
                />
              </Field>
              <Field label="Number of episodes to whitelist from new feed archive">
                <input
                  className="input"
                  type="number"
                  value={pending?.app?.number_of_episodes_to_whitelist_from_archive_of_new_feed ?? 1}
                  onChange={(e) => setField(['app', 'number_of_episodes_to_whitelist_from_archive_of_new_feed'], Number(e.target.value))}
                />
              </Field>
            </div>
          </Section>
          {renderSaveButton()}
        </div>

      {showEnvWarning && envWarningPaths.length > 0 && (
        <EnvOverrideWarningModal
          paths={envWarningPaths}
          overrides={envOverrides}
          onCancel={handleDismissEnvWarning}
          onConfirm={handleConfirmEnvWarning}
        />
      )}
      
      {/* Extra padding to prevent audio player overlay from obscuring bottom settings */}
      <div className="h-24"></div>
      {/* Datalist options rendered once at end to ensure they exist in DOM */}
      <LlmModelDatalist />
    </div>
  );
}

function EnvOverrideWarningModal({
  paths,
  overrides,
  onConfirm,
  onCancel,
}: {
  paths: string[];
  overrides: EnvOverrideMap;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!paths.length) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4 py-6">
      <div className="w-full max-w-lg space-y-4 rounded-lg bg-white p-5 shadow-xl">
        <div>
          <h3 className="text-base font-semibold text-gray-900">Environment-managed settings</h3>
          <p className="text-sm text-gray-600">
            These fields are controlled by environment variables. Update the referenced variables in your
            <code className="mx-1 font-mono text-xs">.env</code>
            (or deployment secrets) to make the change persistent. Saving now will apply it temporarily until the
            service restarts.
          </p>
        </div>
        <ul className="space-y-3 text-sm">
          {paths.map((path) => {
            const meta = overrides[path];
            const label = ENV_FIELD_LABELS[path] ?? path;
            return (
              <li key={path} className="rounded border border-amber-200 bg-amber-50 p-3">
                <div className="font-medium text-gray-900">{label}</div>
                {meta?.env_var ? (
                  <p className="mt-1 text-xs text-gray-700">
                    Managed by <code className="font-mono">{meta.env_var}</code>
                    {meta?.value_preview && (
                      <span className="ml-1 text-gray-600">({meta.value_preview})</span>
                    )}
                    {!meta?.value_preview && meta?.value && (
                      <span className="ml-1 text-gray-600">({meta.value})</span>
                    )}
                  </p>
                ) : (
                  <p className="mt-1 text-xs text-gray-700">Managed by deployment environment</p>
                )}
              </li>
            );
          })}
        </ul>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            Go back
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded bg-gradient-to-r from-purple-600 to-pink-500 px-3 py-2 text-sm font-semibold text-white hover:from-purple-700 hover:to-pink-600"
          >
            Save anyway
          </button>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children, icon }: { title: string; children: ReactNode; icon?: ReactNode }) {
  return (
    <div className="bg-white/80 backdrop-blur-sm rounded-xl border border-purple-200/50 shadow-sm unicorn-card">
      <div className="px-4 py-3 border-b border-purple-100/50 bg-gradient-to-r from-pink-50/50 via-purple-50/50 to-cyan-50/50">
        <h3 className="text-sm font-semibold text-purple-900 flex items-center gap-2">
          {icon}
          {title}
        </h3>
      </div>
      <div className="p-4 space-y-3">{children}</div>
    </div>
  );
}

function Field({
  label,
  children,
  envMeta,
  description,
}: {
  label: string;
  children: ReactNode;
  envMeta?: EnvOverrideEntry;
  description?: string;
}) {
  return (
    <label className="block">
      <div className="flex items-start justify-between gap-3">
        <div className="w-40 flex-shrink-0">
          <span className="block text-sm text-gray-700">{label}</span>
          {description && <span className="block text-xs text-gray-500 mt-0.5">{description}</span>}
          <EnvVarHint meta={envMeta} />
        </div>
        <div className="flex-1">{children}</div>
      </div>
      <style>{`.input{width:100%;padding:0.5rem 0.75rem;border:1px solid #d1d5db;border-radius:0.375rem;font-size:0.875rem;transition:all 0.15s}.input:focus{outline:none;border-color:#3b82f6;box-shadow:0 0 0 2px rgba(59,130,246,0.1)}`}</style>
    </label>
  );
}

function EnvVarHint({ meta }: { meta?: EnvOverrideEntry }) {
  if (!meta?.env_var) {
    return null;
  }

  return (
    <code className="mt-1 block text-xs text-gray-500 font-mono">{meta.env_var}</code>
  );
}

const LLM_MODEL_ALIASES: string[] = [
  // OpenAI aliases
  'openai/gpt-4',
  'openai/gpt-4o',
  // Anthropic
  'anthropic/claude-3.5-sonnet',
  'anthropic/claude-3.5-haiku',
  // Google Gemini
  'gemini/gemini-2.0-flash',
  'gemini/gemini-1.5-pro',
  'gemini/gemini-1.5-flash',
  // Groq popular models
  'groq/openai/gpt-oss-120b',
];

function LlmModelDatalist() {
  return (
    <datalist id="llm-model-datalist">
      {LLM_MODEL_ALIASES.map((m) => (
        <option key={m} value={m} />
      ))}
    </datalist>
  );
}
