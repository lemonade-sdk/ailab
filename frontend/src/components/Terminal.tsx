import { useEffect, useRef } from 'react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';

interface Props {
  containerName: string;
  onClose: () => void;
}

export function Terminal({ containerName, onClose }: Props) {
  const divRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const term = new XTerm({ cursorBlink: true, theme: { background: '#1a1b26' } });
    const fitAddon = new FitAddon();
    const linksAddon = new WebLinksAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(linksAddon);
    term.open(divRef.current!);
    fitAddon.fit();

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${window.location.host}/api/ws/shell/${containerName}`);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
    };
    ws.onmessage = (e) => {
      term.write(new Uint8Array(e.data as ArrayBuffer));
    };
    ws.onclose = () => term.write('\r\n[connection closed]\r\n');

    term.onData((data) => ws.send(new TextEncoder().encode(data)));
    term.onResize(({ cols, rows }) => {
      ws.send(JSON.stringify({ type: 'resize', cols, rows }));
    });

    const ro = new ResizeObserver(() => fitAddon.fit());
    ro.observe(divRef.current!);

    return () => {
      ws.close();
      term.dispose();
      ro.disconnect();
    };
  }, [containerName]);

  return (
    <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50">
      <div className="bg-[#1a1b26] rounded-lg shadow-2xl w-[90vw] h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700">
          <span className="text-gray-300 font-mono text-sm">{containerName} — shell</span>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none">×</button>
        </div>
        <div ref={divRef} className="flex-1 p-2 min-h-0" />
      </div>
    </div>
  );
}
