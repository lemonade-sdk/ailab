#!/usr/bin/env node
'use strict';
// Writes an opinionated ~/.openclaw/openclaw.json that uses lemonade-server
// via its Ollama-compatible API on port 8000.
//
// Using api:"ollama" with the lemonade provider ID gives clean model names
// (lemonade/model-name) instead of the auto-derived custom-127-0-0-1-8000
// display name that openclaw generates for openai-completions custom URLs.
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
  id:      'lemonade',
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

// Static model list used when lemonade is not reachable at install time.
// openclaw will use these until it can refresh from the live API.
const LEMONADE_STATIC_MODELS = PREFERRED_MODELS.map(id => ({
  id,
  name:          id,
  reasoning:     false,
  input:         ['text'],
  cost:          { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  contextWindow: 32768,
  maxTokens:     4096,
}));

function httpGet(url) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: 3000 }, res => {
      if (res.statusCode !== 200) {
        return reject(new Error(`HTTP ${res.statusCode}`));
      }
      let body = '';
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => resolve(body));
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
  });
}

// Probe lemonade's Ollama-compatible /api/tags endpoint.
async function probeOllamaModels(baseUrl) {
  try {
    const body = await httpGet(`${baseUrl}/api/tags`);
    const data = JSON.parse(body).models || [];
    return data.length > 0 ? data : null;
  } catch {
    return null;
  }
}

// Score a model for suitability as a primary chat/agent model.
function modelScore(id) {
  const s = id.toLowerCase();
  if (/flux|sdxl|stable.diff/i.test(s))    return -30;
  if (/kokoro|whisper|tts|speech/i.test(s)) return -20;
  if (/embed|retriev/i.test(s))             return -20;
  let score = 0;
  const prefIdx = PREFERRED_MODELS.indexOf(id);
  if (prefIdx !== -1)                        score += 100 - prefIdx;
  if (s.includes('flm'))                     score += 20;
  if (s.includes('gguf'))                    score += 10;
  if (/instruct|it-|chat/i.test(s))          score +=  5;
  return score;
}

async function main() {
  console.log('ailab: configuring openclaw...');

  // Probe lemonade via the Ollama API.
  const rawModels = await probeOllamaModels(LEMONADE.baseUrl);

  let models;
  let live = false;

  if (rawModels) {
    live = true;
    models = rawModels;
    console.log(`ailab: lemonade found — ${models.length} model(s): ${models.map(m => m.name || m.id).join(', ')}`);
  } else {
    models = LEMONADE_STATIC_MODELS;
    console.log('ailab: lemonade not reachable — pre-configuring with defaults');
    console.log('  (config will be ready once lemonade-server starts on the host)');
  }

  // Normalise model objects: Ollama /api/tags uses 'name', static list uses 'id'.
  const normModels = models.map(m => {
    const id = m.name || m.id;
    return {
      id,
      name:          id,
      reasoning:     false,
      input:         ['text'],
      cost:          { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: m.details?.parameter_size ? undefined : 32768,
      maxTokens:     4096,
    };
  }).filter(m => m.id);

  // Pick the best model as primary.
  const ranked = normModels
    .map(m => ({ id: `lemonade/${m.id}`, score: modelScore(m.id) }))
    .filter(m => m.score >= 0)
    .sort((a, b) => b.score - a.score);

  // Default to Qwen3.5-9B-GGUF if nothing scores (e.g. live model has unusual name).
  const primary = ranked[0]?.id ?? `lemonade/${normModels[0]?.id ?? 'Qwen3.5-9B-GGUF'}`;

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
          api:     LEMONADE.api,   // 'ollama' → clean "lemonade/model" display names
          models:  normModels,
        },
      },
    },
    agents: {
      defaults: {
        workspace: WORKSPACE,
        sandbox:   { mode: 'off' },
        model:     { primary },
      },
    },
  };

  fs.mkdirSync(CONFIG_DIR, { recursive: true });
  fs.mkdirSync(WORKSPACE,  { recursive: true });
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2) + '\n');

  console.log('ailab: openclaw configured');
  console.log(`  config:  ${CONFIG_FILE}`);
  console.log(`  primary: ${primary}`);
  console.log('');
  console.log('  Lemonade → localhost:8000 via Ollama API (proxied from host)');
  console.log('  Cloud providers disabled (models.mode: replace)');
  console.log('  Web UI → http://localhost:18789 (accessible on host)');
}

main().catch(err => {
  console.error(`ailab: setup_openclaw failed: ${err.message}`);
  process.exit(1);
});
