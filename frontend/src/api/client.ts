import { Container, LemonadeRecipe, Package, PortProxy, SSEEvent, SystemUser } from '../types';

// Use Vite's BASE_URL so API calls resolve correctly whether the app is served
// from the root (local: '/') or from a tunnel sub-path (e.g. '/d/device:11500/').
const BASE = `${import.meta.env.BASE_URL}api`;

/**
 * Construct an absolute WebSocket URL for `path` (e.g. '/api/ws/shell/mybox').
 *
 * Local:  ws://localhost:11500/api/ws/shell/mybox
 * Tunnel: wss://hub.example.com/d/framework:11500/api/ws/shell/mybox
 *
 * The hub's WebSocket proxy route mirrors the HTTP route: /d/{target}/{path},
 * so we just prefix with the device segment when running behind the tunnel.
 */
export function wsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const m = window.location.pathname.match(/^(\/d\/[^/]+)\//);
  if (m) {
    return `${proto}//${window.location.host}${m[1]}${path}`;
  }
  return `${proto}//${window.location.host}${path}`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, options);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  return resp.json() as Promise<T>;
}

export async function getContainers(): Promise<Container[]> {
  return request<Container[]>('/containers');
}

export async function getContainer(name: string): Promise<Container> {
  return request<Container>(`/containers/${name}`);
}

export async function startContainer(name: string): Promise<void> {
  await request(`/containers/${name}/start`, { method: 'POST' });
}

export async function stopContainer(name: string): Promise<void> {
  await request(`/containers/${name}/stop`, { method: 'POST' });
}

export async function deleteContainer(name: string): Promise<void> {
  await request(`/containers/${name}`, { method: 'DELETE' });
}

export async function getPorts(name: string): Promise<PortProxy[]> {
  return request<PortProxy[]>(`/containers/${name}/ports`);
}

export async function addPort(
  name: string,
  host_port: number,
  container_port: number,
  direction: string,
): Promise<void> {
  await request(`/containers/${name}/ports`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ host_port, container_port, direction }),
  });
}

export async function removePort(name: string, device: string): Promise<void> {
  await request(`/containers/${name}/ports/${device}`, { method: 'DELETE' });
}

export async function getPortBaseUrl(): Promise<string> {
  const { base } = await request<{ base: string }>('/port-base-url');
  return base;
}

export async function getGatewayUrl(name: string): Promise<{ url: string }> {
  return request<{ url: string }>(`/containers/${name}/gateway-url`);
}

export async function gatewayPairStream(
  name: string,
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  return streamSSE(`${BASE}/containers/${name}/gateway-pair`, {}, onEvent);
}

export async function getUsers(): Promise<SystemUser[]> {
  return request<SystemUser[]>('/users');
}

export async function getPackages(): Promise<Package[]> {
  return request<Package[]>('/packages');
}

export async function streamSSE(
  url: string,
  body: unknown,
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const reader = resp.body!.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop()!;
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          onEvent(JSON.parse(line.slice(6)) as SSEEvent);
        } catch {
          // ignore malformed events
        }
      }
    }
  }
}

export async function createContainerStream(
  name: string,
  packages: string[],
  extraPorts: Array<{ host_port: number; container_port: number }>,
  onEvent: (event: SSEEvent) => void,
  username?: string,
): Promise<void> {
  return streamSSE(`${BASE}/containers/create`, { name, packages, extra_ports: extraPorts, username: username ?? null }, onEvent);
}

export async function installStream(
  name: string,
  pkg: string,
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  return streamSSE(`${BASE}/containers/${name}/install`, { package: pkg }, onEvent);
}

export async function getOpenclawModel(name: string): Promise<{ model: string }> {
  return request<{ model: string }>(`/containers/${name}/openclaw/model`);
}

export async function getLemonadeRecipes(): Promise<LemonadeRecipe[]> {
  return request<LemonadeRecipe[]>('/lemonade/recipes');
}

export async function getLemonadeDownloadedModels(): Promise<string[]> {
  const { downloaded } = await request<{ downloaded: string[] }>('/lemonade/downloaded-models');
  return downloaded;
}

export async function importRecipeStream(
  containerName: string,
  recipe: LemonadeRecipe,
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  return streamSSE(
    `${BASE}/containers/${containerName}/openclaw/import-recipe`,
    { recipe },
    onEvent,
  );
}
