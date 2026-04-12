import { useEffect, useRef } from 'react';
import { wsUrl } from '../api/client';
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
    const term = new XTerm({ cursorBlink: true, theme: { background: '#1a1d26' } });
    const fitAddon = new FitAddon();
    const linksAddon = new WebLinksAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(linksAddon);
    term.open(divRef.current!);

    let ws: WebSocket | null = null;

    function connectWs() {
      ws = new WebSocket(wsUrl(`/api/ws/shell/${containerName}`));
      ws.binaryType = 'arraybuffer';

      ws.onopen = () => {
        ws!.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
      };
      ws.onmessage = (e) => {
        if (typeof e.data === 'string') {
          term.write(e.data);
        } else {
          term.write(new Uint8Array(e.data as ArrayBuffer));
        }
      };
      ws.onclose = () => term.write('\r\n[connection closed]\r\n');

      term.onData((data) => ws!.send(new TextEncoder().encode(data)));
      term.onResize(({ cols, rows }) => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'resize', cols, rows }));
        }
      });
    }

    // Wait for layout so fitAddon gets real dimensions before connecting.
    // requestAnimationFrame fires after the browser paints the flex container.
    requestAnimationFrame(() => {
      fitAddon.fit();
      if (term.cols > 0 && term.rows > 0) {
        connectWs();
      }
      term.focus();
    });

    const ro = new ResizeObserver(() => {
      fitAddon.fit();
      // Connect on first real fit if we haven't yet (fallback for slow layouts)
      if (!ws && term.cols > 0 && term.rows > 0) {
        connectWs();
      }
    });
    ro.observe(divRef.current!);

    return () => {
      if (ws) ws.close();
      term.dispose();
      ro.disconnect();
    };
  }, [containerName]);

  return (
    <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-lg shadow-2xl w-[90vw] h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-4 py-2 border-b border-slate-600">
          <span className="text-slate-300 font-mono text-sm">{containerName} — shell</span>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none">×</button>
        </div>
        <div ref={divRef} className="flex-1 p-2 min-h-0" />
      </div>
    </div>
  );
}
