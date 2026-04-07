import { useEffect, useState } from 'react';
import { PortProxy } from '../types';
import { getPorts, addPort, removePort } from '../api/client';

interface Props {
  containerName: string;
  onClose: () => void;
}

export function PortManager({ containerName, onClose }: Props) {
  const [ports, setPorts] = useState<PortProxy[]>([]);
  const [hostPort, setHostPort] = useState('');
  const [containerPort, setContainerPort] = useState('');
  const [direction, setDirection] = useState<'outbound' | 'inbound'>('outbound');
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState('');

  const refresh = () => {
    setLoading(true);
    getPorts(containerName)
      .then(setPorts)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => { refresh(); }, [containerName]);

  const handleAdd = async () => {
    if (!hostPort || !containerPort) { setError('Both ports are required.'); return; }
    setError('');
    setAdding(true);
    try {
      await addPort(containerName, parseInt(hostPort), parseInt(containerPort), direction);
      setHostPort('');
      setContainerPort('');
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (device: string) => {
    try {
      await removePort(containerName, device);
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 rounded-xl shadow-2xl w-full max-w-lg border border-slate-700 flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <h2 className="text-white font-semibold text-lg">{containerName} — Ports</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none">×</button>
        </div>

        <div className="overflow-y-auto flex-1 p-6 space-y-5">
          {loading ? (
            <p className="text-slate-400 text-sm">Loading…</p>
          ) : ports.length === 0 ? (
            <p className="text-slate-400 text-sm">No port proxies configured.</p>
          ) : (
            <table className="w-full text-sm text-slate-300">
              <thead>
                <tr className="text-slate-500 text-xs uppercase border-b border-slate-700">
                  <th className="text-left pb-2">Device</th>
                  <th className="text-left pb-2">Direction</th>
                  <th className="text-left pb-2">Listen</th>
                  <th className="text-left pb-2">Connect</th>
                  <th className="pb-2"></th>
                </tr>
              </thead>
              <tbody>
                {ports.map((p) => (
                  <tr key={p.device} className="border-b border-slate-700/50">
                    <td className="py-2 font-mono text-xs">{p.device}</td>
                    <td className="py-2">
                      <span className={`text-xs px-1.5 py-0.5 rounded ${p.direction === 'outbound' ? 'bg-blue-900/50 text-blue-300' : 'bg-purple-900/50 text-purple-300'}`}>
                        {p.direction}
                      </span>
                    </td>
                    <td className="py-2 font-mono text-xs text-slate-400">{p.listen}</td>
                    <td className="py-2 font-mono text-xs text-slate-400">{p.connect}</td>
                    <td className="py-2">
                      <button
                        onClick={() => handleRemove(p.device)}
                        className="text-red-400 hover:text-red-300 text-xs"
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="border-t border-slate-700 pt-4">
            <h3 className="text-slate-300 text-sm font-medium mb-3">Add port proxy</h3>
            <div className="flex gap-2 mb-3">
              <input
                value={hostPort}
                onChange={(e) => setHostPort(e.target.value)}
                placeholder="Host port"
                className="flex-1 bg-slate-700 text-white px-3 py-2 rounded border border-slate-600 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <input
                value={containerPort}
                onChange={(e) => setContainerPort(e.target.value)}
                placeholder="Container port"
                className="flex-1 bg-slate-700 text-white px-3 py-2 rounded border border-slate-600 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
            <div className="flex gap-4 mb-3 text-sm text-slate-300">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="direction"
                  value="outbound"
                  checked={direction === 'outbound'}
                  onChange={() => setDirection('outbound')}
                  className="accent-indigo-500"
                />
                Outbound (host→container)
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="direction"
                  value="inbound"
                  checked={direction === 'inbound'}
                  onChange={() => setDirection('inbound')}
                  className="accent-indigo-500"
                />
                Inbound (container→host)
              </label>
            </div>
            {error && <p className="text-red-400 text-xs mb-2">{error}</p>}
            <button
              onClick={handleAdd}
              disabled={adding}
              className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium"
            >
              {adding ? 'Adding…' : 'Add Port'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
