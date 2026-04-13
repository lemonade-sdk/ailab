> Historical design note: this document captures an early plan for AI Lab Cloud
> and no longer matches the current implementation in every detail. Prefer the
> `ailab` and `ailab-cloud` READMEs plus the current source code for the
> supported tunnel protocol and configuration surface.

This project specification outlines the architecture, implementation details, and project plan for **AI Lab Cloud**, a secure tunneling and identity bridge for the AI Lab ecosystem.

### Project Overview: AI Lab Cloud
The goal is to provide a "Cloud-assisted Direct Access" model. AI Lab Cloud will serve as a rendezvous point and authenticated proxy, allowing you to access your home-based LXD agent containers from any public network without configuring complex VPNs or port forwarding.

---

### 1. Architecture & Core Components


#### A. AI Lab Cloud (The Hub)
* **Role:** Authenticates users via GitHub OAuth, maintains active persistent connections from Home Devices, and proxies HTTP/WebSocket traffic.
* **Hosting:** Cannot be hosted on GitHub Pages (which is for static content only). It requires a long-running process to manage WebSockets. A Linode/DigitalOcean VPS is ideal.
* **Stack:** Python (FastAPI), `uvicorn`, `authlib` (GitHub OAuth), and `redis` (to track active tunnel registrations).

#### B. The Tunnel Agent (Integrated into AI Lab)
* **Role:** A background service in the existing `ailab` codebase that initiates an outbound connection to the Cloud Hub.
* **Mechanism:** Uses **Reverse WebSockets** or **gRPC stream**. It establishes a TLS-encrypted connection to the Cloud Hub and "listens" for incoming requests to proxy locally.

#### C. Request Flow
1.  **Handshake:** Home AI Lab instance connects to `ailab.linuxgroove.com` with a signed JWT containing the GitHub Username allowed.
2.  **Rendezvous:** Cloud Hub holds the connection open.
3.  **Authentication:** User visits the Cloud URL, logs in via GitHub.
4.  **Proxying:** The Cloud Hub matches the logged-in GitHub user to the Home Device's permitted user list and pipes the browser traffic through the established WebSocket tunnel to the local AI Lab FastAPI app.

---

### 2. Technical Specification

#### Identity & Authentication
* **Protocol:** GitHub OAuth 2.0.
* **Authorization:** The Home Device configuration will include an `allowed_github_users` list. The Cloud Hub will only route traffic if the `sub` (user ID/login) from the OAuth flow matches the registered tunnel's permitted list.

#### Tunneling Implementation
To handle both the AI Lab Web UI and the various agent ports (OpenClaw, etc.), we will implement a **Host-Header-based Multiplexer**:
* `https://[device-id].ailab.linuxgroove.com` -> Proxies to AI Lab Web UI (Port 11500).
* `https://[device-id]-[port].ailab.linuxgroove.com` -> Proxies to specific agent ports (e.g., 18789 for OpenClaw).

#### Changes Required in `ailab` Codebase
1.  **New Module (`ailab/cloud.py`):** A background task using `aiohttp` to maintain the tunnel connection.
2.  **Configuration Update:** Add `cloud_host` and `cloud_user` to the snap settings/config.
3.  **Middleware modification in `ailab/web/app.py`:** Update CORS and Trusted Host settings to allow the cloud domain as a valid origin.

---

### 3. Project Plan

#### Phase 1: The Cloud Hub (MVP)
* Develop the FastAPI backend for `ailab-cloud`.
* Implement GitHub OAuth flow.
* Create a "Tunnel Registry" in Redis to map GitHub IDs to active WebSocket connections.

#### Phase 2: The Tunnel Client
* Modify `ailab/container.py` and `ailab/web/app.py` to include a `CloudTunnelManager`.
* Implement the protocol to wrap local HTTP requests into WebSocket frames to be sent back to the Cloud Hub.
* **Security:** Ensure the Home Device verifies the Cloud Hub's TLS certificate to prevent Man-in-the-Middle attacks.

#### Phase 3: Port Multiplexing
* Implement logic to automatically detect which ports AI Lab is currently forwarding (e.g., 7860, 8888, 18789) and register those subdomains with the Cloud Hub.
* Handle WebSocket proxying for the integrated terminal (`/api/ws/shell/{name}`) to ensure the CLI remains interactive over the cloud.

#### Phase 4: Deployment & Branding
* Dockerize the Cloud Hub for easy deployment on Linode.
* Configure Nginx/Traefik as a reverse proxy for the Cloud Hub to handle wildcard SSL certificates (essential for the `[port].ailab...` subdomains).

---

### 4. Implementation Example (Conceptual Tunnel Client)

[Inference] This snippet demonstrates how the existing `ailab` service would initiate the connection:

```python
# Proposed addition to ailab/cloud.py
async def maintain_tunnel(cloud_url, allowed_user):
    async with aiohttp.ClientSession() as session:
        # Authenticate with the cloud hub
        async with session.ws_connect(f"{cloud_url}/register/{allowed_user}") as ws:
            async for msg in ws:
                # Receive a proxied request from the cloud
                request_data = json.loads(msg.data)
                # Forward to local AI Lab Web UI (Port 11500)
                local_resp = await forward_to_local(request_data)
                # Send response back through tunnel
                await ws.send_json(local_resp)
```

### Sources Used:
* `README.md`: Provided details on existing ports and `ailab web` defaults.
* `ailab/web/app.py`: Detail on FastAPI implementation and WebSocket shell handling.
* `ailab/container.py`: Information on how LXD proxy devices are managed.

########################################################

Building the **AI Lab Cloud** hub as a snap package for Linode deployment is a strategic choice, as it ensures the service has the same transactional updates and security confinement as the `ailab` client itself.

### Implementation Specification: `ailab-cloud` Snap

To host the cloud service on a Linode VPS, you will need a new project structure that packages a FastAPI-based "Hub" and an Nginx/Traefik reverse proxy to handle the wildcard subdomains for individual agent ports.

#### 1. Snap Architecture
The snap will be configured as a `server` type application, containing the FastAPI application and necessary runtime dependencies.



**Key Snapcraft Components:**
* **Base:** `core24` (matching the Ubuntu 24.04 recommendation for AI Lab).
* **Confinement:** `strict` (requires specific interfaces for network access).
* **Plugs:** `network`, `network-bind`, and `redis-support`.

#### 2. `snapcraft.yaml` for AI Lab Cloud
```yaml
name: ailab-cloud
version: '0.1'
summary: Public hub for AI Lab remote access
description: |
  Provides a secure tunneling rendezvous and GitHub OAuth gateway
  for AI Lab instances.
base: core24
confinement: strict

apps:
  hub:
    command: bin/python -m uvicorn ailab_cloud.main:app --host 0.0.0.0 --port 8080
    daemon: simple
    plugs: [network, network-bind]
    environment:
      GITHUB_CLIENT_ID: ${SNAP_COMMON}/github_id
      GITHUB_CLIENT_SECRET: ${SNAP_COMMON}/github_secret

parts:
  ailab-cloud:
    plugin: python
    source: .
    python-packages:
      - fastapi
      - uvicorn
      - authlib
      - redis
      - aiohttp
```

### 3. Core Service Logic (The Bridge)

The cloud service must manage two distinct types of connections:
1.  **The Control Plane (WebSocket):** The home `ailab` instance connects here and maintains a persistent "Tunnel".
2.  **The Data Plane (HTTP/WS):** When you browse to `ailab.linuxgroove.com`, the Hub verifies your GitHub session, looks up the active tunnel for `kenvandine`, and pipes your request through the control plane to the home device.

**Integrated Agent Port Forwarding:**
The Cloud Hub will automatically create subdomains or path-based routing for the standard AI Lab ports:
* **18789:** OpenClaw.
* **3000:** Nullclaw.
* **11500:** AI Lab Web UI.

### 4. Integration Plan for Existing `ailab` Codebase

To support this Linode-hosted snap, the following modifications are needed in the files you provided:

* **`ailab/web/app.py`:** Add a new background task that runs alongside the FastAPI app. This task will use `aiohttp` to initiate a connection to your Linode instance.
* **`snap/snapcraft.yaml`:** Add a new configuration hook (`snap/hooks/configure`) to allow you to set the cloud endpoint via the CLI:
    ```bash
    snap set ailab cloud.enabled=true
    snap set ailab cloud.host=https://ailab.linuxgroove.com
    snap set ailab cloud.user=kenvandine
    ```
* **`ailab/container.py`:** Modify the `INBOUND_PROXIES` logic to ensure that traffic coming from the cloud tunnel is treated as local traffic, bypassing standard IP-based restrictions while maintaining user-mapping security.

### 5. Deployment on Linode
1.  **Provision:** Create a standard Ubuntu 24.04 Linode.
2.  **Install Snapd:** `sudo apt install snapd`.
3.  **Install Hub:** `sudo snap install ailab-cloud`.
4.  **DNS:** Configure a wildcard A record: `*.ailab.linuxgroove.com` pointing to the Linode IP. This is critical for routing traffic to specific containers/ports dynamically.
