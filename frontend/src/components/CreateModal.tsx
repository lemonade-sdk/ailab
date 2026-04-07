import { useState, useEffect, useRef } from 'react';
import { Package, SSEEvent } from '../types';
import { getPackages, createContainerStream } from '../api/client';

interface Props {
  onClose: () => void;
  onDone: () => void;
}

export function CreateModal({ onClose, onDone }: Props) {
  const [name, setName] = useState('');
  const [packages, setPackages] = useState<Package[]>([]);
  const [selectedPackages, setSelectedPackages] = useState<string[]>([]);
  const [extraPorts, setExtraPorts] = useState<Array<{ host: string; container: string }>>([]);
  const [log, setLog] = useState('');
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const logRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    getPackages().then(setPackages).catch(console.error);
  }, []);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [log]);

  const togglePackage = (name: string) => {
    setSelectedPackages((prev) =>
      prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name],
    );
  };

  const addPortRow = () => setExtraPorts((prev) => [...prev, { host: '', container: '' }]);
  const removePortRow = (i: number) => setExtraPorts((prev) => prev.filter((_, idx) => idx !== i));
  const updatePort = (i: number, field: 'host' | 'container', value: string) => {
    setExtraPorts((prev) => prev.map((p, idx) => (idx === i ? { ...p, [field]: value } : p)));
  };

  const handleSubmit = async () => {
    if (!name.trim()) { setError('Name is required.'); return; }
    setError('');
    setRunning(true);
    setLog('');

    const ports = extraPorts
      .filter((p) => p.host && p.container)
      .map((p) => ({ host_port: parseInt(p.host), container_port: parseInt(p.container) }));

    try {
      await createContainerStream(name.trim(), selectedPackages, ports, (event: SSEEvent) => {
        if (event.type === 'log') setLog((prev) => prev + event.msg + '\n');
        else if (event.type === 'done') setDone(true);
        else if (event.type === 'error') { setError(event.msg); setDone(true); }
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 rounded-xl shadow-2xl w-full max-w-lg border border-slate-700 flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <h2 className="text-white font-semibold text-lg">New Container</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none">×</button>
        </div>

        <div className="overflow-y-auto p-6 space-y-5 flex-1">
          <div>
            <label className="block text-sm text-slate-300 mb-1">Container name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={running}
              placeholder="mybox"
              className="w-full bg-slate-700 text-white px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm disabled:opacity-50"
            />
          </div>

          {packages.length > 0 && (
            <div>
              <label className="block text-sm text-slate-300 mb-2">Packages</label>
              <div className="space-y-2">
                {packages.map((pkg) => (
                  <label key={pkg.name} className="flex items-start gap-3 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={selectedPackages.includes(pkg.name)}
                      onChange={() => togglePackage(pkg.name)}
                      disabled={running}
                      className="mt-0.5 accent-indigo-500"
                    />
                    <span>
                      <span className="text-sm text-slate-200 font-medium">{pkg.name}</span>
                      <span className="text-xs text-slate-400 ml-2">{pkg.description}</span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          )}

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm text-slate-300">Extra ports (HOST:CONTAINER)</label>
              <button
                onClick={addPortRow}
                disabled={running}
                className="text-xs text-indigo-400 hover:text-indigo-300 disabled:opacity-50"
              >
                + Add port
              </button>
            </div>
            {extraPorts.map((p, i) => (
              <div key={i} className="flex gap-2 mb-2">
                <input
                  value={p.host}
                  onChange={(e) => updatePort(i, 'host', e.target.value)}
                  placeholder="Host port"
                  className="flex-1 bg-slate-700 text-white px-3 py-1.5 rounded border border-slate-600 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
                <span className="text-slate-500 self-center">:</span>
                <input
                  value={p.container}
                  onChange={(e) => updatePort(i, 'container', e.target.value)}
                  placeholder="Container port"
                  className="flex-1 bg-slate-700 text-white px-3 py-1.5 rounded border border-slate-600 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
                <button onClick={() => removePortRow(i)} className="text-slate-500 hover:text-red-400 px-1">✕</button>
              </div>
            ))}
          </div>

          {log && (
            <div>
              <label className="block text-sm text-slate-400 mb-1">Output</label>
              <textarea
                ref={logRef}
                readOnly
                value={log}
                className="w-full h-40 bg-slate-900 text-green-400 text-xs font-mono p-3 rounded border border-slate-700 resize-none"
              />
            </div>
          )}

          {error && <p className="text-red-400 text-sm">{error}</p>}
        </div>

        <div className="px-6 py-4 border-t border-slate-700 flex justify-end gap-3">
          {done ? (
            <button
              onClick={onDone}
              className="bg-indigo-600 hover:bg-indigo-500 text-white px-5 py-2 rounded-lg text-sm font-medium"
            >
              Done
            </button>
          ) : (
            <>
              <button
                onClick={onClose}
                disabled={running}
                className="text-slate-400 hover:text-white px-4 py-2 text-sm disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={running || !name.trim()}
                className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-5 py-2 rounded-lg text-sm font-medium"
              >
                {running ? 'Creating…' : 'Create'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
