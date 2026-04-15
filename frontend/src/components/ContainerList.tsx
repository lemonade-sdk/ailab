import { useEffect, useState } from 'react';
import { Container } from '../types';
import { startContainer, stopContainer, deleteContainer, getGatewayUrl, getPortBaseUrl, gatewayPairStream, getOpenclawModel } from '../api/client';
import { SSEEvent } from '../types';

interface Props {
  containers: Container[];
  onShell: (name: string) => void;
  onLogs: (name: string) => void;
  onPorts: (name: string) => void;
  onInstall: (name: string) => void;
  onChangeModel: (name: string, currentModel: string | null) => void;
  onRefresh: () => void;
  modelRefreshTick: number;
}

// Known tool gateway ports — containers with these ports have an app installed.
const GATEWAY_PORTS: Record<number, string> = {
  18789: 'openclaw',
  3000:  'nullclaw',
  18800: 'picoclaw',
};

// Port used by openclaw — URL includes an auth token so it's always fetched from the API.
const OPENCLAW_PORT_FOR_URL = 18789;

// Port used by openclaw — used to detect whether to fetch the configured model.
const OPENCLAW_PORT = 18789;

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
      } else if (event.type === 'done') {
        setDone(true);
        // Fetch the URL from the API — it will be tunnel-aware.
        getGatewayUrl(name).then(({ url }) => {
          if (!cancelled) setPairedUrl(url);
        }).catch(() => {});
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
            <button onClick={handleOpen} className="px-4 py-2 bg-lemon-500 hover:bg-lemon-400 text-slate-950 font-semibold text-sm rounded transition-colors">
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
  const [loading, setLoading] = useState(true);

  const fetchUrl = () => {
    setLoading(true);
    if (port !== OPENCLAW_PORT_FOR_URL) {
      // Non-token ports: ask the server for the base URL so tunnel routing works.
      getPortBaseUrl()
        .then((base) => setUrl(`${base}:${port}`))
        .catch(() => setUrl(`http://localhost:${port}`))
        .finally(() => setLoading(false));
      return;
    }
    getGatewayUrl(name)
      .then(({ url }) => { setUrl(url); setNotPaired(false); })
      .catch((err) => {
        if (String(err).includes('404')) {
          setNotPaired(true);
        } else {
          getPortBaseUrl()
            .then((base) => setUrl(`${base}:${port}`))
            .catch(() => setUrl(`http://localhost:${port}`));
        }
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchUrl(); }, [name, port]);

  useEffect(() => {
    if (!notPaired) return;
    const interval = setInterval(fetchUrl, 5000);
    return () => clearInterval(interval);
  }, [notPaired, name, port]);

  if (loading || (!url && !notPaired)) {
    return (
      <span className="inline-flex items-center justify-center w-full bg-slate-700/50 text-slate-400 text-xs px-3 py-2 rounded-lg">
        …
      </span>
    );
  }

  if (notPaired) {
    return (
      <>
        <button
          onClick={() => setShowPairModal(true)}
          className="inline-flex items-center justify-center gap-1.5 w-full bg-amber-800 hover:bg-amber-700 text-amber-100 text-sm font-medium px-3 py-2 rounded-lg transition-colors"
          title="Gateway not paired — click to pair and open"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
      href={url ?? '#'}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center justify-center gap-2 w-full bg-lemon-500/15 hover:bg-lemon-500/25 border border-lemon-500/40 text-lemon-400 text-sm font-medium px-3 py-2 rounded-lg transition-colors"
    >
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
      </svg>
      Open {label}
    </a>
  );
}

/** Strip "lemonade/" and "user." prefixes for display. */
function displayModel(model: string): string {
  return model.replace(/^lemonade\//, '').replace(/^user\./, '');
}

interface CardProps {
  container: Container;
  onShell: (name: string) => void;
  onLogs: (name: string) => void;
  onPorts: (name: string) => void;
  onInstall: (name: string) => void;
  onChangeModel: (name: string, currentModel: string | null) => void;
  onStart: (name: string) => void;
  onStop: (name: string) => void;
  onDelete: (name: string) => void;
  modelRefreshTick: number;
}

function ContainerCard({
  container: c,
  onShell, onLogs, onPorts, onInstall, onChangeModel,
  onStart, onStop, onDelete, modelRefreshTick,
}: CardProps) {
  const running = c.status.toLowerCase() === 'running';
  const gateways = c.outbound_ports
    .filter((p) => p in GATEWAY_PORTS)
    .map((p) => ({ port: p, label: GATEWAY_PORTS[p] }));

  const hasApp = gateways.length > 0;
  const hasOpenclaw = c.outbound_ports.includes(OPENCLAW_PORT);

  const [currentModel, setCurrentModel] = useState<string | null>(null);
  const [showDetails, setShowDetails] = useState(false);

  useEffect(() => {
    if (!hasOpenclaw) return;
    getOpenclawModel(c.name)
      .then(({ model }) => setCurrentModel(model))
      .catch(() => setCurrentModel(null));
  }, [hasOpenclaw, c.name, modelRefreshTick]);

  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-5 flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-white font-semibold text-base truncate">{c.name}</h3>
        <StatusBadge status={c.status} />
      </div>

      {/* Gateway open button */}
      {running && gateways.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {gateways.map(({ port, label }) => (
            <GatewayButton key={port} name={c.name} port={port} label={label} />
          ))}
        </div>
      )}

      {/* Model row */}
      {hasOpenclaw && currentModel && (
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-slate-500 text-xs shrink-0">Model</span>
          <span className="text-lemon-400 text-xs font-medium truncate flex-1" title={currentModel}>
            {displayModel(currentModel)}
          </span>
          {running && (
            <button
              onClick={() => onChangeModel(c.name, currentModel)}
              className="shrink-0 text-xs text-slate-400 hover:text-white bg-slate-700 hover:bg-slate-600 px-2 py-0.5 rounded transition-colors"
            >
              Change
            </button>
          )}
        </div>
      )}

      {/* Primary actions */}
      <div className="flex flex-wrap gap-2">
        {running && (
          <button
            onClick={() => onShell(c.name)}
            className="flex-1 min-w-[4rem] bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs py-1.5 px-2 rounded transition-colors"
          >
            Shell
          </button>
        )}
        {running && !hasApp && (
          <button
            onClick={() => onInstall(c.name)}
            className="flex-1 min-w-[4rem] bg-lemon-500/15 hover:bg-lemon-500/25 border border-lemon-500/40 text-lemon-400 text-xs py-1.5 px-2 rounded transition-colors"
          >
            Install
          </button>
        )}
        {running ? (
          <button
            onClick={() => onStop(c.name)}
            className="flex-1 min-w-[4rem] bg-slate-700 hover:bg-slate-600 text-amber-300/80 text-xs py-1.5 px-2 rounded transition-colors"
          >
            Stop
          </button>
        ) : (
          <button
            onClick={() => onStart(c.name)}
            className="flex-1 min-w-[4rem] bg-slate-700 hover:bg-slate-600 text-green-400/80 text-xs py-1.5 px-2 rounded transition-colors"
          >
            Start
          </button>
        )}
        <button
          onClick={() => onDelete(c.name)}
          className="flex-1 min-w-[4rem] bg-slate-700 hover:bg-slate-600 text-red-400/80 text-xs py-1.5 px-2 rounded transition-colors"
        >
          Delete
        </button>
      </div>

      {/* Details expander */}
      <div className="border-t border-slate-700 pt-2">
        <button
          onClick={() => setShowDetails((v) => !v)}
          className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors w-full"
        >
          <svg
            className={`w-3 h-3 transition-transform ${showDetails ? 'rotate-90' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          Details
        </button>

        {showDetails && (
          <div className="mt-2 space-y-2 text-xs text-slate-400">
            <div><span className="text-slate-500">IPv4</span> <span className="ml-1">{c.ipv4 || '—'}</span></div>
            {c.outbound_ports.length > 0 && (
              <div className="flex flex-wrap gap-1 items-center">
                <span className="text-slate-500">Ports</span>
                {c.outbound_ports.map((p) => (
                  <span key={p} className="bg-slate-700 text-slate-300 px-1.5 py-0.5 rounded">
                    :{p}
                  </span>
                ))}
              </div>
            )}
            <div className="flex gap-2 pt-1">
              {running && (
                <button
                  onClick={() => onLogs(c.name)}
                  className="bg-slate-700 hover:bg-slate-600 text-slate-200 py-1 px-3 rounded transition-colors"
                >
                  Logs
                </button>
              )}
              <button
                onClick={() => onPorts(c.name)}
                className="bg-slate-700 hover:bg-slate-600 text-slate-200 py-1 px-3 rounded transition-colors"
              >
                Ports
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ConfirmModal({ message, onConfirm, onCancel }: { message: string; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 rounded-xl border border-slate-700 w-full max-w-sm p-6 flex flex-col gap-5 shadow-2xl">
        <p className="text-white text-sm">{message}</p>
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm bg-slate-700 hover:bg-slate-600 text-red-400/80 rounded-lg transition-colors"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

export function ContainerList({ containers, onShell, onLogs, onPorts, onInstall, onChangeModel, onRefresh, modelRefreshTick }: Props) {
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

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
    try { await deleteContainer(name); onRefresh(); } catch (e) { alert(String(e)); }
    setConfirmDelete(null);
  };

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {containers.map((c) => (
          <ContainerCard
            key={c.name}
            container={c}
            onShell={onShell}
            onLogs={onLogs}
            onPorts={onPorts}
            onInstall={onInstall}
            onChangeModel={onChangeModel}
            onStart={handleStart}
            onStop={handleStop}
            onDelete={(name) => setConfirmDelete(name)}
            modelRefreshTick={modelRefreshTick}
          />
        ))}
      </div>
      {confirmDelete && (
        <ConfirmModal
          message={`Delete container "${confirmDelete}"? This cannot be undone.`}
          onConfirm={() => handleDelete(confirmDelete)}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </>
  );
}
