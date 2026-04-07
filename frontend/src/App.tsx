import { useEffect, useState } from 'react';
import { Container } from './types';
import { getContainers } from './api/client';
import { ContainerList } from './components/ContainerList';
import { CreateModal } from './components/CreateModal';
import { Terminal } from './components/Terminal';
import { LogStream } from './components/LogStream';
import { PortManager } from './components/PortManager';
import { InstallModal } from './components/InstallModal';

export default function App() {
  const [containers, setContainers] = useState<Container[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [shellContainer, setShellContainer] = useState<string | null>(null);
  const [logsContainer, setLogsContainer] = useState<string | null>(null);
  const [portsContainer, setPortsContainer] = useState<string | null>(null);
  const [installContainer, setInstallContainer] = useState<string | null>(null);
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
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl font-bold text-white">ailab</span>
          <span className="text-slate-400 text-sm">LXD sandbox manager</span>
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
            onRefresh={refresh}
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
    </div>
  );
}
