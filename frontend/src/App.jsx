
import React, { useState, useEffect, useCallback } from 'react';
import './index.css'; // Ensure CSS is loaded

const API_BASE = "http://localhost:8000";

const StatusIcon = ({ status }) => {
  switch (status) {
    case 'processing': return <div className="w-2 h-2 rounded-full bg-blue-500 animate-ping" />;
    case 'completed': return <span className="text-green-400 text-lg">✓</span>;
    case 'failed': return <span className="text-red-500 text-lg">✕</span>;
    case 'skipped': return <span className="text-orange-400 text-lg">∅</span>;
    default: return <div className="w-2 h-2 rounded-full bg-gray-600" />;
  }
};

function App() {
  const [queue, setQueue] = useState([]);
  const [appState, setAppState] = useState({ paused: false, processing_id: null });
  const [isDragOver, setIsDragOver] = useState(false);
  const [dragCounter, setDragCounter] = useState(0);

  const fetchQueue = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/queue`);
      const data = await res.json();
      setQueue(data);
    } catch (e) {
      console.error("Queue fetch failed", e);
    }
  }, []);

  const fetchState = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/state`);
      const data = await res.json();
      setAppState(data);
    } catch (e) {
      console.error("State fetch failed", e);
    }
  }, []);

  useEffect(() => {
    fetchQueue();
    fetchState();
    const interval = setInterval(() => {
      fetchQueue();
      fetchState();
    }, 1000);
    return () => clearInterval(interval);
  }, [fetchQueue, fetchState]);

  const handleDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragCounter(prev => prev + 1);
    setIsDragOver(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragCounter(prev => prev - 1);
    if (dragCounter <= 1) {
      setIsDragOver(false);
    }
  };

  const handleDrop = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    setDragCounter(0);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      let duplicates = 0;
      let uploaded = 0;

      for (const file of e.dataTransfer.files) {
        const formData = new FormData();
        formData.append('file', file);
        try {
          const res = await fetch(`${API_BASE}/upload`, { method: 'POST', body: formData });
          if (res.status === 409) {
            duplicates++;
          } else if (res.ok) {
            uploaded++;
          }
        } catch (err) {
          console.error("Upload failed", err);
        }
      }

      if (duplicates > 0) {
        // Could use a nice toast here instead of alert, but alert ensures they see it.
        // For "extremely nice UI", we should probably avoid native alert, but simpler for now.
        console.warn(`Skipped ${duplicates} duplicates.`);
      }

      fetchQueue();
    }
  };

  const handleControl = async (action) => {
    await fetch(`${API_BASE}/control/${action}`, { method: 'POST' });
    fetchState();
  };

  const handleSkip = async (id) => {
    await fetch(`${API_BASE}/control/skip/${id}`, { method: 'POST' });
    fetchQueue();
  }

  // Calculate stats
  const completedCount = queue.filter(i => i.status === 'completed').length;
  const processingCount = queue.filter(i => i.status === 'processing').length;
  const queuedCount = queue.filter(i => i.status === 'queued').length;

  return (
    <div
      className="min-h-screen bg-black text-gray-200 selection:bg-blue-500/30 font-sans flex flex-col relative overflow-hidden"
      onDragEnter={handleDragEnter}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Background Ambience */}
      <div className="fixed top-[-20%] left-[-10%] w-[50%] h-[50%] bg-blue-900/20 rounded-full blur-[120px] pointer-events-none" />
      <div className="fixed bottom-[-20%] right-[-10%] w-[50%] h-[50%] bg-purple-900/20 rounded-full blur-[120px] pointer-events-none" />

      {/* Main Container */}
      <div className="flex-1 flex flex-col max-w-5xl mx-auto w-full p-8 z-10">

        {/* Header */}
        <header className="flex items-end justify-between mb-10 pb-6 border-b border-white/5">
          <div>
            <h1 className="text-4xl font-semibold tracking-tight text-white mb-2">StemGen</h1>
            <div className="flex items-center gap-3 text-sm font-medium text-gray-400">
              <span className={`flex items-center gap-2 px-2 py-1 rounded-md ${appState.paused ? 'bg-yellow-500/10 text-yellow-400' : 'bg-green-500/10 text-green-400'}`}>
                <div className={`w-1.5 h-1.5 rounded-full ${appState.paused ? 'bg-yellow-400' : 'bg-green-400 animate-pulse'}`} />
                {appState.paused ? "PAUSED" : "ACTIVE"}
              </span>
              <span>•</span>
              <span>{queue.length} Tracks In Queue</span>
            </div>
          </div>

          <div className="flex gap-3">
            {!appState.paused ? (
              <button onClick={() => handleControl('pause')} className="glass-button px-6 py-2 rounded-full text-sm font-medium hover:bg-white/10 flex items-center gap-2 group">
                <span className="group-hover:text-yellow-400 transition-colors">⏸ Pause Batch</span>
              </button>
            ) : (
              <button onClick={() => handleControl('resume')} className="glass-button px-6 py-2 rounded-full text-sm font-medium hover:bg-white/10 flex items-center gap-2 group">
                <span className="group-hover:text-green-400 transition-colors">▶ Resume Batch</span>
              </button>
            )}
          </div>
        </header>

        {/* Hero Drop Zone (Only visible if queue is empty) */}
        {queue.length === 0 && (
          <div className={`
                flex-1 flex flex-col items-center justify-center border-2 border-dashed rounded-3xl transition-all duration-500
                ${isDragOver ? 'border-blue-500 bg-blue-500/5 scale-100 shadow-[0_0_50px_rgba(59,130,246,0.2)]' : 'border-white/10 hover:border-white/20 hover:bg-white/5 scale-95 opacity-80'}
            `}>
            <div className="text-7xl mb-6 opacity-50 transition-transform duration-500 group-hover:scale-110">
              ✨
            </div>
            <h2 className="text-3xl font-semibold text-white mb-3">Drop Audio Files</h2>
            <p className="text-gray-400 text-lg max-w-md text-center">
              Drag and drop your MP3s here to begin separation.
              <br /><span className="text-sm opacity-60 mt-2 block">Supports batch processing & auto-deduplication.</span>
            </p>
          </div>
        )}

        {/* Queue Display */}
        {queue.length > 0 && (
          <div className="flex-1 overflow-visible">
            {/* Progress Stats */}
            <div className="grid grid-cols-3 gap-4 mb-8">
              <div className="glass-panel p-4 rounded-2xl">
                <div className="text-gray-400 text-xs font-semibold uppercase tracking-wider mb-1">In Queue</div>
                <div className="text-2xl font-bold text-white">{queuedCount}</div>
              </div>
              <div className="glass-panel p-4 rounded-2xl relative overflow-hidden group">
                <div className="absolute inset-0 bg-blue-500/10 opacity-0 group-hover:opacity-100 transition-opacity" />
                <div className="text-blue-400 text-xs font-semibold uppercase tracking-wider mb-1">Processing</div>
                <div className="text-2xl font-bold text-white flex items-center gap-2">
                  {processingCount}
                  {processingCount > 0 && <span className="flex h-3 w-3 relative"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span><span className="relative inline-flex rounded-full h-3 w-3 bg-blue-500"></span></span>}
                </div>
              </div>
              <div className="glass-panel p-4 rounded-2xl">
                <div className="text-green-400 text-xs font-semibold uppercase tracking-wider mb-1">Completed</div>
                <div className="text-2xl font-bold text-white">{completedCount}</div>
              </div>
            </div>

            {/* List */}
            <div className="space-y-3 pb-20">
              {queue.map((item, index) => (
                <div key={item.id} className={`
                             animate-slide-up
                             glass-panel p-4 rounded-xl flex items-center gap-5 group hover:bg-white/5 transition-all
                             ${item.status === 'processing' ? 'ring-1 ring-blue-500/30 bg-blue-500/5' : ''}
                         `} style={{ animationDelay: `${Math.min(index * 50, 500)}ms` }}>

                  {/* Icon */}
                  <div className={`
                                 w-12 h-12 rounded-lg flex items-center justify-center text-lg font-bold shadow-lg
                                 ${item.status === 'completed' ? 'bg-gradient-to-br from-green-500 to-emerald-700 text-white' :
                      item.status === 'processing' ? 'bg-gradient-to-br from-blue-500 to-indigo-700 text-white' :
                        item.status === 'failed' ? 'bg-red-500/20 text-red-500' :
                          'bg-gray-800 text-gray-500'}
                             `}>
                    {item.status === 'completed' ? 'STEM' : '♫'}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-center mb-1">
                      <h3 className="font-medium text-white truncate pr-4 text-base">
                        {item.filename.replace(/^\d+_/, '').replace(/^[a-f0-9-]{36}_/, '')}
                      </h3>
                      <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                        {item.status}
                      </span>
                    </div>

                    {/* Progress Bar */}
                    <div className="h-1.5 w-full bg-gray-800/50 rounded-full overflow-hidden relative">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ease-out relative
                                            ${item.status === 'failed' ? 'bg-red-500' :
                            item.status === 'completed' ? 'bg-green-500' :
                              'bg-gradient-to-r from-blue-500 to-purple-500'}
                                         `}
                        style={{ width: `${item.progress}%` }}
                      >
                        {item.status === 'processing' && (
                          <div className="absolute inset-0 bg-white/20 animate-pulse" />
                        )}
                      </div>
                    </div>
                    {item.error && <p className="text-red-400 text-xs mt-1.5">{item.error}</p>}
                  </div>

                  {/* Actions */}
                  <div className="w-24 flex justify-end">
                    {item.status === 'completed' ? (
                      <a
                        href={`${API_BASE}/download/${item.id}`}
                        className="glass-button px-4 py-1.5 rounded-lg text-xs font-semibold text-white hover:bg-green-500/20 hover:border-green-500/50 transition-all"
                      >
                        SAVE
                      </a>
                    ) : ['queued', 'processing'].includes(item.status) ? (
                      <button
                        onClick={() => handleSkip(item.id)}
                        className="p-2 hover:bg-white/10 rounded-full text-gray-400 hover:text-white transition-colors"
                        title="Skip"
                      >
                        <span className="text-lg leading-none">×</span>
                      </button>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

      </div>

      {/* Full Screen Overlay for Drag */}
      {isDragOver && (
        <div className="fixed inset-0 bg-blue-500/10 backdrop-blur-sm z-50 flex items-center justify-center pointer-events-none border-8 border-blue-500/30 transition-all duration-300">
          <div className="text-center animate-bounce">
            <div className="text-6xl mb-4">📂</div>
            <h2 className="text-4xl font-bold text-white drop-shadow-lg">Release to Upload</h2>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
