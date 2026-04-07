import { Container } from '../types';
import { startContainer, stopContainer, deleteContainer } from '../api/client';

interface Props {
  containers: Container[];
  onShell: (name: string) => void;
  onLogs: (name: string) => void;
  onPorts: (name: string) => void;
  onInstall: (name: string) => void;
  onRefresh: () => void;
}

function StatusBadge({ status }: { status: string }) {
  const isRunning = status.toLowerCase() === 'running';
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${
        isRunning
          ? 'bg-green-900/50 text-green-400 ring-1 ring-green-500/30'
          : 'bg-slate-700 text-slate-400 ring-1 ring-slate-600'
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${isRunning ? 'bg-green-400' : 'bg-slate-500'}`} />
      {status}
    </span>
  );
}

export function ContainerList({ containers, onShell, onLogs, onPorts, onInstall, onRefresh }: Props) {
  if (containers.length === 0) {
    return (
      <div className="text-center mt-24">
        <p className="text-slate-400 text-lg">No containers yet.</p>
        <p className="text-slate-500 text-sm mt-1">Click <strong className="text-slate-300">+ New Container</strong> to get started.</p>
      </div>
    );
  }

  const handleStart = async (name: string) => {
    try { await startContainer(name); onRefresh(); } catch (e) { alert(String(e)); }
  };
  const handleStop = async (name: string) => {
    try { await stopContainer(name); onRefresh(); } catch (e) { alert(String(e)); }
  };
  const handleDelete = async (name: string) => {
    if (!confirm(`Delete container "${name}"?`)) return;
    try { await deleteContainer(name); onRefresh(); } catch (e) { alert(String(e)); }
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {containers.map((c) => {
        const running = c.status.toLowerCase() === 'running';
        return (
          <div key={c.name} className="bg-slate-800 rounded-xl border border-slate-700 p-5 flex flex-col gap-3">
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-white font-semibold text-lg truncate">{c.name}</h3>
              <StatusBadge status={c.status} />
            </div>

            <div className="text-sm text-slate-400 space-y-1">
              <div><span className="text-slate-500">IPv4:</span> {c.ipv4 || '—'}</div>
              <div className="flex flex-wrap gap-1 items-center">
                <span className="text-slate-500">Ports:</span>
                {c.outbound_ports.length === 0
                  ? <span>—</span>
                  : c.outbound_ports.map((p) => (
                    <span key={p} className="bg-slate-700 text-slate-300 text-xs px-1.5 py-0.5 rounded">
                      :{p}
                    </span>
                  ))}
              </div>
            </div>

            <div className="flex flex-wrap gap-2 mt-auto pt-2 border-t border-slate-700">
              {running && (
                <button
                  onClick={() => onShell(c.name)}
                  className="flex-1 min-w-[4rem] bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs py-1.5 px-2 rounded transition-colors"
                >
                  Shell
                </button>
              )}
              {running && (
                <button
                  onClick={() => onLogs(c.name)}
                  className="flex-1 min-w-[4rem] bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs py-1.5 px-2 rounded transition-colors"
                >
                  Logs
                </button>
              )}
              <button
                onClick={() => onPorts(c.name)}
                className="flex-1 min-w-[4rem] bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs py-1.5 px-2 rounded transition-colors"
              >
                Ports
              </button>
              {running && (
                <button
                  onClick={() => onInstall(c.name)}
                  className="flex-1 min-w-[4rem] bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs py-1.5 px-2 rounded transition-colors"
                >
                  Install
                </button>
              )}
              {running ? (
                <button
                  onClick={() => handleStop(c.name)}
                  className="flex-1 min-w-[4rem] bg-amber-800 hover:bg-amber-700 text-amber-100 text-xs py-1.5 px-2 rounded transition-colors"
                >
                  Stop
                </button>
              ) : (
                <button
                  onClick={() => handleStart(c.name)}
                  className="flex-1 min-w-[4rem] bg-green-800 hover:bg-green-700 text-green-100 text-xs py-1.5 px-2 rounded transition-colors"
                >
                  Start
                </button>
              )}
              <button
                onClick={() => handleDelete(c.name)}
                className="flex-1 min-w-[4rem] bg-red-900 hover:bg-red-800 text-red-100 text-xs py-1.5 px-2 rounded transition-colors"
              >
                Delete
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
