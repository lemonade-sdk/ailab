import { useEffect, useState } from 'react';
import { Container } from '../types';
import { startContainer, stopContainer, deleteContainer, getGatewayUrl, gatewayPairStream } from '../api/client';
import { SSEEvent } from '../types';

interface Props {
  containers: Container[];
  onShell: (name: string) => void;
  onLogs: (name: string) => void;
  onPorts: (name: string) => void;
  onInstall: (name: string) => void;
  onRefresh: () => void;
}

// Known tool gateway ports — containers with these ports get an "Open" link.
const GATEWAY_PORTS: Record<number, string> = {
  18789: 'openclaw',
  3000:  'nullclaw',
  18800: 'picoclaw',
};

// Ports that use token-based auth — URL fetched from API rather than constructed client-side.
const TOKEN_AUTH_PORTS = new Set([18789]);

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

function PairModal({ name, onClose, onPaired }: { name: string; onClose: () => void; onPaired: (url: string) => void }) {
  const [logs, setLogs] = useState<string[]>(['Starting gateway pairing…']);
  const [done, setDone] = useState(false);
  const [pairedUrl, setPairedUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    gatewayPairStream(name, (event: SSEEvent) => {
      if (cancelled) return;
      if (event.type === 'log') {
        setLogs(prev => [...prev, event.msg ?? '']);
        // Extract URL from the success log line
        const match = (event.msg ?? '').match(/http:\/\/localhost:\d+\/#token=\S+/);
        if (match) setPairedUrl(match[0]);
      } else if (event.type === 'done') {
        setDone(true);
      } else if (event.type === 'error') {
        setLogs(prev => [...prev, `Error: ${event.msg}`]);
        setDone(true);
      }
    }).catch(err => {
      if (!cancelled) {
        setLogs(prev => [...prev, `Error: ${String(err)}`]);
        setDone(true);
      }
    });
    return () => { cancelled = true; };
  }, [name]);

  const handleOpen = () => {
    if (pairedUrl) {
      onPaired(pairedUrl);
      window.open(pairedUrl, '_blank', 'noopener,noreferrer');
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 rounded-xl border border-slate-700 w-full max-w-lg p-6 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h2 className="text-white font-semibold text-lg">Pairing openclaw gateway</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none">✕</button>
        </div>
        <div className="bg-slate-900 rounded-lg p-3 font-mono text-xs text-slate-300 h-40 overflow-y-auto">
          {logs.map((l, i) => <div key={i}>{l}</div>)}
          {!done && <div className="text-slate-500 animate-pulse">…</div>}
        </div>
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm rounded transition-colors">
            Close
          </button>
          {done && pairedUrl && (
            <button onClick={handleOpen} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded transition-colors">
              Open openclaw
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function GatewayButton({ name, port, label }: { name: string; port: number; label: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [notPaired, setNotPaired] = useState(false);
  const [showPairModal, setShowPairModal] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!TOKEN_AUTH_PORTS.has(port)) {
      setUrl(`http://localhost:${port}`);
      return;
    }
    setLoading(true);
    getGatewayUrl(name)
      .then(({ url }) => { setUrl(url); setNotPaired(false); })
      .catch((err) => {
        if (String(err).includes('404')) {
          setNotPaired(true);
        } else {
          setUrl(`http://localhost:${port}`);
        }
      })
      .finally(() => setLoading(false));
  }, [name, port]);

  if (loading) {
    return (
      <span className="inline-flex items-center bg-indigo-900/40 text-indigo-400 text-xs px-3 py-1.5 rounded">
        …
      </span>
    );
  }

  if (notPaired) {
    return (
      <>
        <button
          onClick={() => setShowPairModal(true)}
          className="inline-flex items-center gap-1.5 bg-amber-800 hover:bg-amber-700 text-amber-100 text-xs font-medium px-3 py-1.5 rounded transition-colors"
          title="Gateway not paired — click to pair and open"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M10.172 13.828a4 4 0 015.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
          </svg>
          Pair {label}
        </button>
        {showPairModal && (
          <PairModal
            name={name}
            onClose={() => setShowPairModal(false)}
            onPaired={(pairedUrl) => { setUrl(pairedUrl); setNotPaired(false); }}
          />
        )}
      </>
    );
  }

  return (
    <a
      href={url ?? `http://localhost:${port}`}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1.5 bg-indigo-700 hover:bg-indigo-600 text-white text-xs font-medium px-3 py-1.5 rounded transition-colors"
    >
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
      </svg>
      Open {label}
    </a>
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
        const gateways = c.outbound_ports
          .filter((p) => p in GATEWAY_PORTS)
          .map((p) => ({ port: p, label: GATEWAY_PORTS[p] }));

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

            {running && gateways.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {gateways.map(({ port, label }) => (
                  <GatewayButton key={port} name={c.name} port={port} label={label} />
                ))}
              </div>
            )}

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
