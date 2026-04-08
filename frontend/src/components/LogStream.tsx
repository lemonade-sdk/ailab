import { useEffect, useRef, useState } from 'react';

interface Props {
  containerName: string;
  onClose: () => void;
}

export function LogStream({ containerName, onClose }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const preRef = useRef<HTMLPreElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${window.location.host}/api/ws/logs/${containerName}`);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      setLines((prev) => {
        const next = [...prev, String(e.data)];
        return next.length > 500 ? next.slice(next.length - 500) : next;
      });
    };
    ws.onerror = () => setLines((prev) => [...prev, '[WebSocket error]']);
    ws.onclose = () => setLines((prev) => [...prev, '[connection closed]']);

    return () => ws.close();
  }, [containerName]);

  useEffect(() => {
    if (preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [lines]);

  const handleClear = () => setLines([]);

  return (
    <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50">
      <div className="bg-slate-900 rounded-lg shadow-2xl w-[90vw] h-[80vh] flex flex-col border border-slate-700">
        <div className="flex items-center justify-between px-4 py-2 border-b border-slate-700">
          <span className="text-slate-300 font-mono text-sm">{containerName} — logs</span>
          <div className="flex items-center gap-3">
            <button
              onClick={handleClear}
              className="text-slate-400 hover:text-white text-xs px-2 py-1 rounded hover:bg-slate-700 transition-colors"
            >
              Clear
            </button>
            <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none">×</button>
          </div>
        </div>
        <pre
          ref={preRef}
          className="flex-1 overflow-y-auto p-4 text-xs font-mono text-green-400 bg-slate-900 rounded-b-lg whitespace-pre-wrap break-all"
        >
          {lines.join('\n')}
        </pre>
      </div>
    </div>
  );
}
