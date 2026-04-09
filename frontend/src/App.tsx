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
      <header className="bg-slate-800 border-b border-slate-600 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center shrink-0">
            <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-white font-medium text-base tracking-tight">AI Lab</span>
            <span className="text-slate-400 text-xs font-light">Your AI in a Box</span>
          </div>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
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
