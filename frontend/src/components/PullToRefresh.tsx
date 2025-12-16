import type { ReactNode } from 'react';
import { usePullToRefresh } from '../hooks/usePullToRefresh';

interface PullToRefreshProps {
  onRefresh: () => Promise<void>;
  children: ReactNode;
  className?: string;
  disabled?: boolean;
}

export function PullToRefresh({ onRefresh, children, className = '', disabled = false }: PullToRefreshProps) {
  const { isRefreshing, pullDistance, containerRef } = usePullToRefresh({
    onRefresh,
    disabled,
  });

  const showIndicator = pullDistance > 10 || isRefreshing;
  const indicatorOpacity = Math.min(pullDistance / 60, 1);
  const indicatorScale = Math.min(pullDistance / 80, 1);

  return (
    <div 
      ref={containerRef} 
      className={`relative overflow-y-auto overscroll-contain ${className}`}
      style={{ WebkitOverflowScrolling: 'touch' }}
    >
      {/* Pull indicator */}
      {showIndicator && (
        <div 
          className="absolute left-0 right-0 flex justify-center pointer-events-none z-10"
          style={{ 
            top: Math.max(pullDistance - 50, 0),
            opacity: indicatorOpacity,
            transform: `scale(${indicatorScale})`,
            transition: isRefreshing ? 'none' : 'opacity 0.1s, transform 0.1s',
          }}
        >
          <div className={`
            flex items-center justify-center w-10 h-10 rounded-full 
            bg-gradient-to-br from-purple-500 to-pink-500 shadow-lg
            ${isRefreshing ? 'animate-spin' : ''}
          `}>
            {isRefreshing ? (
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
            ) : (
              <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
              </svg>
            )}
          </div>
        </div>
      )}
      
      {/* Content with pull offset */}
      <div 
        style={{ 
          transform: pullDistance > 0 ? `translateY(${pullDistance}px)` : 'none',
          transition: pullDistance === 0 && !isRefreshing ? 'transform 0.2s ease-out' : 'none',
        }}
      >
        {children}
      </div>
    </div>
  );
}
