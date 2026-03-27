#!/usr/bin/env node
'use strict';
// Writes an opinionated ~/.openclaw/openclaw.json that uses lemonade-server
// via a custom "lemonade" provider that speaks the Ollama API on port 8000.
//
// The openclaw config is intentionally limited to a single "lemonade"
// provider so all cloud and alternate local providers are disabled.
//
// Ollama (port 11434) is intentionally omitted from the openclaw config to
// avoid spurious discovery errors when it isn't running.  The port proxy
// still exists on the container so other tools can reach it.
//
// Adapted from ubuclaw/snap/local/bin/setup-providers.js.

const http = require('http');
const fs   = require('fs');
const path = require('path');
const os   = require('os');

// lemonade exposes an Ollama-compatible API at port 8000.
const LEMONADE = {
  baseUrl: 'http://localhost:8000',
  apiKey:  'lemonade',
  api:     'ollama',
};

const HOME        = os.homedir();
// Honour per-container config paths set by the installer; fall back to defaults.
const CONFIG_DIR  = process.env.OPENCLAW_STATE_DIR  || path.join(HOME, '.openclaw');
const CONFIG_FILE = process.env.OPENCLAW_CONFIG_PATH || path.join(CONFIG_DIR, 'openclaw.json');
const WORKSPACE   = path.join(HOME, 'workspace');

// Preferred Qwen models in priority order (highest preference first).
const PREFERRED_MODELS = [
  'Qwen3.5-27B-GGUF',
  'Qwen3.5-9B-GGUF',
  'Qwen3-8B-GGUF',
  'Qwen3.5-4B-GGUF',
  'Qwen3-4B-GGUF',
  'Qwen3.5-2B-GGUF',
  'Qwen3-1.7B-GGUF',
];

const FALLBACK_MODEL = 'Qwen3.5-9B-GGUF';

function httpRequest(method, url, body) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const options = {
      method,
      timeout: 5000,
      headers: data ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {},
    };
    const req = http.request(url, options, res => {
      let body = '';
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          return reject(new Error(`HTTP ${res.statusCode}`));
        }
        resolve(body);
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    if (data) {
      req.write(data);
    }
    req.end();
  });
}

// Probe lemonade via the Ollama /api/tags endpoint — this returns all available
// models (including undownloaded ones), unlike the OpenAI /models endpoint which
// only lists already-downloaded models.
async function probeOllamaModels() {
  try {
    const body = await httpRequest('GET', 'http://localhost:8000/api/tags');
    const data = JSON.parse(body).models || [];
    return data.length > 0 ? data : null;
  } catch {
    return null;
  }
}

async function pullLemonadeModel(modelName) {
  try {
    await httpRequest('POST', 'http://localhost:8000/api/v1/pull', { model_name: modelName });
    return true;
  } catch {
    return false;
  }
}

function choosePreferredModel(downloadedIds) {
  for (const preferred of PREFERRED_MODELS) {
    if (downloadedIds.has(preferred)) {
      return preferred;
    }
  }
  return null;
}

async function main() {
  console.log('ailab: configuring openclaw...');

  // Probe lemonade via the Ollama API.
  const rawModels = await probeOllamaModels();

  let modelIds = [];
  let primaryModel = FALLBACK_MODEL;

  if (rawModels) {
    modelIds = rawModels
      .map(m => m.name || m.id)
      .filter(Boolean);
    console.log(`ailab: lemonade found — ${modelIds.length} model(s): ${modelIds.join(', ')}`);
  } else {
    console.log('ailab: lemonade not reachable — pre-configuring with defaults');
    console.log('  (config will be ready once lemonade-server starts on the host)');
  }

  const downloadedIds = new Set(modelIds);
  const preferredModel = choosePreferredModel(downloadedIds);
  if (preferredModel) {
    primaryModel = preferredModel;
  } else {
    if (!downloadedIds.has(FALLBACK_MODEL)) {
      const pullStarted = await pullLemonadeModel(FALLBACK_MODEL);
      if (pullStarted) {
        console.log(`ailab: requested lemonade download for fallback model ${FALLBACK_MODEL}`);
      } else if (rawModels) {
        console.log(`ailab: could not request lemonade download for ${FALLBACK_MODEL}`);
      }
    }
    downloadedIds.add(FALLBACK_MODEL);
  }

  const normModels = Array.from(downloadedIds).map(id => ({
    id,
    name:          id,
    reasoning:     false,
    input:         ['text'],
    cost:          { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 4096,
    maxTokens:     2048,
  }));

  const config = {
    gateway: {
      mode: 'local',
      auth: { mode: 'token' },
    },
    models: {
      // 'replace' mode: only the explicitly listed providers are available.
      // This disables all cloud providers (OpenAI, Anthropic, etc.) by default.
      mode: 'replace',
      providers: {
        lemonade: {
          baseUrl: LEMONADE.baseUrl,
          apiKey:  LEMONADE.apiKey,
          api:     LEMONADE.api,
          models:  normModels,
        },
      },
    },
    agents: {
      defaults: {
        workspace:    WORKSPACE,
        sandbox:      { mode: 'off' },
        model:        { primary: `lemonade/${primaryModel}` },
      },
    },
  };

  fs.mkdirSync(CONFIG_DIR, { recursive: true });
  fs.mkdirSync(WORKSPACE,  { recursive: true });
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2) + '\n');

  console.log('ailab: openclaw configured');
  console.log(`  config:  ${CONFIG_FILE}`);
  console.log(`  primary: lemonade/${primaryModel}`);
  console.log('');
  console.log('  Provider: lemonade only');
  console.log('  Lemonade → localhost:8000 via Ollama API (proxied from host)');
  console.log('  All non-lemonade providers disabled (models.mode: replace)');
  console.log('  Web UI → http://localhost:18789 (accessible on host)');
}

main().catch(err => {
  console.error(`ailab: setup_openclaw failed: ${err.message}`);
  process.exit(1);
});
