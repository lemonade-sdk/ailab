#!/usr/bin/env node
'use strict';
// Probes for local Lemonade and Ollama instances and writes an opinionated
// ~/.openclaw/openclaw.json that prefers Lemonade over Ollama.
//
// If neither service is reachable right now the config is still written with
// both providers pre-configured so openclaw starts correctly once the host
// services are up (the ai-dev-box port proxies wire them to localhost).
//
// Adapted from ubuclaw/snap/local/bin/setup-providers.js.

const http = require('http');
const fs   = require('fs');
const path = require('path');
const os   = require('os');

const PROVIDERS = [
  {
    id:      'lemonade',
    baseUrl: 'http://localhost:8000/api/v1',
    apiKey:  'lemonade',
    api:     'openai-completions',
  },
  {
    id:      'ollama',
    baseUrl: 'http://localhost:11434/v1',
    apiKey:  'ollama',
    api:     'openai-completions',
  },
];

const HOME        = os.homedir();
const CONFIG_DIR  = path.join(HOME, '.openclaw');
const CONFIG_FILE = path.join(CONFIG_DIR, 'openclaw.json');
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

// Static model definitions used when a provider is unreachable at install time.
// openclaw will use these as its model list until it can refresh.
const LEMONADE_STATIC_MODELS = PREFERRED_MODELS.map(id => ({
  id,
  name:          id,
  reasoning:     false,
  input:         ['text'],
  cost:          { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  contextWindow: 32768,
  maxTokens:     4096,
}));

const OLLAMA_STATIC_MODELS = [
  { id: 'llama3.2',    name: 'llama3.2',    contextWindow: 131072, maxTokens: 4096 },
  { id: 'qwen2.5:7b',  name: 'qwen2.5:7b',  contextWindow: 131072, maxTokens: 4096 },
  { id: 'mistral',     name: 'mistral',      contextWindow: 32768,  maxTokens: 4096 },
].map(m => ({
  ...m,
  reasoning: false,
  input: ['text'],
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
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

async function probeModels(baseUrl) {
  try {
    const body = await httpGet(`${baseUrl}/models`);
    const data = JSON.parse(body).data || [];
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

function buildProviderConfig(p, rawModels) {
  return {
    baseUrl: p.baseUrl,
    apiKey:  p.apiKey,
    api:     p.api,
    models:  rawModels.map(m => ({
      id:            m.id,
      name:          m.id,
      reasoning:     false,
      input:         ['text'],
      cost:          { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: m.context_window || 32768,
      maxTokens:     m.max_tokens    || 4096,
    })),
  };
}

async function main() {
  console.log('ai-dev-box: configuring openclaw...');

  const discovered = [];

  for (const p of PROVIDERS) {
    const models = await probeModels(p.baseUrl);
    if (models) {
      discovered.push({ ...p, models, live: true });
      console.log(`ai-dev-box: found ${p.id} with ${models.length} model(s): ${models.map(m => m.id).join(', ')}`);
    } else {
      console.log(`ai-dev-box: ${p.id} not reachable now — pre-configuring with defaults (proxy will connect when host service starts)`);
      // Still include the provider with static defaults so openclaw is ready.
      const staticModels = p.id === 'lemonade' ? LEMONADE_STATIC_MODELS : OLLAMA_STATIC_MODELS;
      discovered.push({ ...p, models: staticModels, live: false });
    }
  }

  // Build provider configs and ranked model list (live providers first, then static).
  const providers = {};
  const modelIds  = [];

  for (const p of discovered) {
    providers[p.id] = buildProviderConfig(p, p.models);
    const ranked = p.models
      .map(m => ({ id: `${p.id}/${m.id}`, score: modelScore(m.id), live: p.live }))
      .filter(m => m.score >= 0)
      .sort((a, b) => {
        // Live providers rank above static ones at the same score.
        if (a.live !== b.live) return a.live ? -1 : 1;
        return b.score - a.score;
      });
    modelIds.push(...ranked.map(m => m.id));
  }

  const [primary, ...fallbacks] = modelIds;

  const config = {
    gateway: {
      mode: 'local',
      auth: { mode: 'token' },
    },
    models: {
      // 'replace' mode: only use the explicitly configured local providers.
      // Cloud providers (OpenAI, Anthropic, etc.) are not shown by default.
      mode: 'replace',
      providers,
    },
    agents: {
      defaults: {
        workspace: WORKSPACE,
        sandbox:   { mode: 'off' },
        model:     { primary, ...(fallbacks.length > 0 && { fallbacks }) },
      },
    },
  };

  fs.mkdirSync(CONFIG_DIR, { recursive: true });
  fs.mkdirSync(WORKSPACE,  { recursive: true });
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2) + '\n');

  console.log(`ai-dev-box: openclaw configured`);
  console.log(`  config:    ${CONFIG_FILE}`);
  console.log(`  primary:   ${primary}`);
  if (fallbacks.length > 0) {
    console.log(`  fallbacks: ${fallbacks.slice(0, 3).join(', ')}${fallbacks.length > 3 ? '…' : ''}`);
  }
  console.log('');
  console.log('  Lemonade → localhost:8000  (proxied from host)');
  console.log('  Ollama   → localhost:11434 (proxied from host)');
  console.log('  Web UI   → http://localhost:18789 (accessible on host)');
}

main().catch(err => {
  console.error(`ai-dev-box: setup_openclaw failed: ${err.message}`);
  process.exit(1);
});
