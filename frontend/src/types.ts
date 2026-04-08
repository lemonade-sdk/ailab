export interface Container {
  name: string;
  status: 'Running' | 'Stopped' | string;
  ipv4: string;
  outbound_ports: number[];
  config_dir: string;
}

export interface PortProxy {
  device: string;
  direction: 'outbound' | 'inbound';
  listen: string;
  connect: string;
}

export interface Package {
  name: string;
  description: string;
}

export interface SystemUser {
  username: string;
  uid: number;
  home: string;
}

export type SSEEvent =
  | { type: 'log'; msg: string }
  | { type: 'done' }
  | { type: 'error'; msg: string };
