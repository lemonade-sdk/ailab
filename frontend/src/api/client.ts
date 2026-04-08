import { Container, Package, PortProxy, SSEEvent, SystemUser } from '../types';

const BASE = '/api';

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
