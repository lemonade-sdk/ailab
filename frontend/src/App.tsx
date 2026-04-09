import { useEffect, useState } from 'react';
import { Container } from './types';
import { getContainers } from './api/client';
import { ContainerList } from './components/ContainerList';
import { CreateModal } from './components/CreateModal';
import { Terminal } from './components/Terminal';
import { LogStream } from './components/LogStream';
import { PortManager } from './components/PortManager';
import { InstallModal } from './components/InstallModal';
import { ChangeModelModal } from './components/ChangeModelModal';

export default function App() {
  const [containers, setContainers] = useState<Container[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [shellContainer, setShellContainer] = useState<string | null>(null);
  const [logsContainer, setLogsContainer] = useState<string | null>(null);
  const [portsContainer, setPortsContainer] = useState<string | null>(null);
  const [installContainer, setInstallContainer] = useState<string | null>(null);
  const [changeModelContainer, setChangeModelContainer] = useState<{ name: string; model: string | null } | null>(null);
  const [modelRefreshTick, setModelRefreshTick] = useState(0);
  const [loading, setLoading] = useState(true);

  const refresh = () => {
    getContainers()
      .then(setContainers)
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      <header className="bg-slate-950 border-b border-slate-700 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <svg className="w-8 h-8 shrink-0" viewBox="0 0 32 32" fill="none">
            <ellipse cx="16" cy="17" rx="11" ry="12" fill="url(#lemon-body)" />
            <path d="M16 5 Q18 2 21 3" stroke="#6aab2e" strokeWidth="1.5" strokeLinecap="round" fill="none" />
            <ellipse cx="16" cy="17" rx="11" ry="12" fill="none" stroke="#d4a800" strokeWidth="0.5" opacity="0.4" />
            <defs>
              <radialGradient id="lemon-body" cx="40%" cy="35%" r="65%">
                <stop offset="0%" stopColor="#ffe580" />
                <stop offset="60%" stopColor="#ffc832" />
                <stop offset="100%" stopColor="#e6a800" />
              </radialGradient>
            </defs>
          </svg>
          <div className="flex flex-col leading-tight">
            <span className="text-white font-semibold text-base tracking-tight">AI Lab</span>
            <span className="text-slate-400 text-xs font-light">Your AI in a Box</span>
          </div>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-lemon-500 hover:bg-lemon-400 text-slate-950 font-semibold px-4 py-2 rounded-lg text-sm transition-colors"
        >
          + New Container
        </button>
      </header>

      <main className="p-6">
        {loading ? (
          <div className="text-slate-400 text-center mt-16">Loading containers…</div>
        ) : (
          <ContainerList
            containers={containers}
            onShell={setShellContainer}
            onLogs={setLogsContainer}
            onPorts={setPortsContainer}
            onInstall={setInstallContainer}
            onChangeModel={(name, model) => setChangeModelContainer({ name, model })}
            onRefresh={refresh}
            modelRefreshTick={modelRefreshTick}
          />
        )}
      </main>

      {showCreate && (
        <CreateModal
          onClose={() => setShowCreate(false)}
          onDone={() => { setShowCreate(false); refresh(); }}
        />
      )}
      {shellContainer && (
        <Terminal containerName={shellContainer} onClose={() => setShellContainer(null)} />
      )}
      {logsContainer && (
        <LogStream containerName={logsContainer} onClose={() => setLogsContainer(null)} />
      )}
      {portsContainer && (
        <PortManager containerName={portsContainer} onClose={() => setPortsContainer(null)} />
      )}
      {installContainer && (
        <InstallModal
          containerName={installContainer}
          onClose={() => setInstallContainer(null)}
          onDone={() => { setInstallContainer(null); refresh(); }}
        />
      )}
      {changeModelContainer && (
        <ChangeModelModal
          containerName={changeModelContainer.name}
          currentModel={changeModelContainer.model}
          onClose={() => setChangeModelContainer(null)}
          onDone={() => {
            setChangeModelContainer(null);
            refresh();
            setModelRefreshTick((t) => t + 1);
          }}
        />
      )}
    </div>
  );
}
