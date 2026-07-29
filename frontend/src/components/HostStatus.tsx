import { useEffect, useState } from 'react';
import { getHostStatus } from '../api/client';
import { HostStatus as HostStatusData } from '../types';

function Indicator({ ok, label, title }: { ok: boolean; label: string; title: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap" title={title}>
      <span className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-green-400' : 'bg-slate-500'}`} />
      {label}
    </span>
  );
}

export function HostStatus() {
  const [status, setStatus] = useState<HostStatusData | null>(null);

  useEffect(() => {
    let active = true;
    const load = () => {
      getHostStatus()
        .then((s) => { if (active) setStatus(s); })
        .catch(() => { /* auth/connection errors handled elsewhere */ });
    };
    load();
    const id = setInterval(load, 10000);
    return () => { active = false; clearInterval(id); };
  }, []);

  if (!status) return null;

  const { lemonade, ollama, cloud } = status;

  return (
    <div className="flex items-center gap-4 text-xs text-slate-400">
      <Indicator
        ok={lemonade.reachable}
        label={lemonade.reachable && lemonade.port ? `lemonade :${lemonade.port}` : 'lemonade'}
        title={lemonade.reachable ? `lemonade-server reachable on :${lemonade.port}` : 'lemonade-server not reachable on the host'}
      />
      <Indicator
        ok={ollama.reachable}
        label="ollama"
        title={ollama.reachable ? 'ollama reachable on :11434' : 'ollama not reachable on the host'}
      />
      {cloud.configured && (
        <Indicator
          ok={cloud.connected}
          label={cloud.connected && cloud.device ? `cloud · ${cloud.device}` : 'cloud'}
          title={
            cloud.connected
              ? `Cloud tunnel connected to ${cloud.host} as ${cloud.device}`
              : 'Cloud tunnel configured but not connected'
          }
        />
      )}
    </div>
  );
}
