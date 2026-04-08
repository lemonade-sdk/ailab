import { useEffect, useRef, useState } from 'react';
import { Package, SSEEvent } from '../types';
import { getPackages, installStream } from '../api/client';

interface Props {
  containerName: string;
  onClose: () => void;
  onDone: () => void;
}

export function InstallModal({ containerName, onClose, onDone }: Props) {
  const [packages, setPackages] = useState<Package[]>([]);
  const [selected, setSelected] = useState('');
  const [log, setLog] = useState('');
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const logRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    getPackages().then((pkgs) => {
      setPackages(pkgs);
      if (pkgs.length > 0) setSelected(pkgs[0].name);
    }).catch(console.error);
  }, []);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [log]);

  const handleInstall = async () => {
    if (!selected) return;
    setError('');
    setRunning(true);
    setLog('');
    try {
      await installStream(containerName, selected, (event: SSEEvent) => {
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
      <div className="bg-slate-800 rounded-xl shadow-2xl w-full max-w-md border border-slate-700 flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <h2 className="text-white font-semibold text-lg">Install package — {containerName}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none">×</button>
        </div>

        <div className="overflow-y-auto flex-1 p-6 space-y-4">
          <div>
            <label className="block text-sm text-slate-300 mb-1">Package</label>
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              disabled={running}
              className="w-full bg-slate-700 text-white px-3 py-2 rounded-lg border border-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
            >
              {packages.filter((pkg) => !['nullclaw', 'picoclaw'].includes(pkg.name)).map((pkg) => (
                <option key={pkg.name} value={pkg.name}>
                  {pkg.name} — {pkg.description}
                </option>
              ))}
            </select>
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
                onClick={handleInstall}
                disabled={running || !selected}
                className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-5 py-2 rounded-lg text-sm font-medium"
              >
                {running ? 'Installing…' : 'Install'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
