#!/usr/bin/env node
'use strict';
// Writes an opinionated ~/.openclaw/openclaw.json that uses lemonade-server
// via a custom "lemonade" provider that speaks the OpenAI-compatible
// completions API.
//
// The lemonade provider is set as the primary model so it is the default
// when opening a new chat.  Other built-in cloud providers remain visible
// but lemonade is pre-selected and ready to use without any API keys.
//
// Adapted from ubuclaw/snap/local/bin/setup-providers.js.

const { spawnSync } = require('child_process');
const fs            = require('fs');
const path          = require('path');
const os            = require('os');

// lemonade-server changed its default port from 8000 to 13305 in version 10.1.
// Try the new port first; fall back to 8000 for older installations.
const LEMONADE_PORTS = [13305, 8000];

function detectLemonadePort() {
  for (const port of LEMONADE_PORTS) {
    const result = spawnSync('curl', [
      '-fsS',
      '--connect-timeout', '2',
      '--max-time', '3',
      `http://localhost:${port}/api/v1/models`,
    ], { encoding: 'utf8', timeout: 4000 });
    if (result.status === 0) {
      return port;
    }
  }
  // Neither port is reachable — default to the new port (>= 10.1).
  return LEMONADE_PORTS[0];
}

const LEMONADE_PORT = detectLemonadePort();
const LEMONADE = {
  baseUrl: `http://localhost:${LEMONADE_PORT}/api/v1`,
  apiKey:  'lemonade',
  api:     'openai-completions',
};

const HOME        = os.homedir();
const CONFIG_DIR  = path.join(HOME, '.openclaw');
const CONFIG_FILE = path.join(CONFIG_DIR, 'openclaw.json');
const WORKSPACE   = path.join(HOME, 'workspace');

// Preferred models in priority order (highest preference first).
const PREFERRED_MODELS = [
  'Qwen3.5-9B-GGUF',
  'Qwen3-8B-GGUF',
  'Qwen3-4B-Instruct-2507-GGUF',
  'Qwen3.5-4B-GGUF',
  'Qwen3-4B-GGUF',
  'Qwen3.5-2B-GGUF',
  'Qwen3-1.7B-GGUF',
];

const FALLBACK_MODEL = 'Qwen3-4B-Instruct-2507-GGUF';

function runCurl(args) {
  const result = spawnSync('curl', args, {
    encoding: 'utf8',
    timeout: 5000,
  });

  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    const stderr = (result.stderr || '').trim();
    throw new Error(stderr || `curl exited with status ${result.status}`);
  }

  return result.stdout;
}

function probeDownloadedModels(baseUrl) {
  try {
    const body = runCurl([
      '-fsS',
      '--connect-timeout', '3',
      '--max-time', '5',
      `${baseUrl}/models`,
    ]);
    const data = JSON.parse(body);
    const models = Array.isArray(data.data) ? data.data : [];
    return models
      .map(model => model.id || model.name)
      .filter(Boolean);
  } catch {
    return null;
  }
}

function pullLemonadeModel(baseUrl, modelName) {
  try {
    runCurl([
      '-fsS',
      '--connect-timeout', '3',
      '--max-time', '5',
      '-X', 'POST',
      '-H', 'Content-Type: application/json',
      '-d', JSON.stringify({ model_name: modelName }),
      `${baseUrl}/pull`,
    ]);
    return true;
  } catch {
    return false;
  }
}

function loadLemonadeModel(baseUrl, modelName) {
  try {
    runCurl([
      '-fsS',
      '--connect-timeout', '3',
      '--max-time', '10',
      '-X', 'POST',
      '-H', 'Content-Type: application/json',
      '-d', JSON.stringify({ model_name: modelName }),
      `${baseUrl}/load`,
    ]);
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

function sortModelsForConfig(modelIds) {
  const preferredRank = new Map(PREFERRED_MODELS.map((id, index) => [id, index]));
  return Array.from(new Set(modelIds)).sort((a, b) => {
    const aRank = preferredRank.has(a) ? preferredRank.get(a) : Number.MAX_SAFE_INTEGER;
    const bRank = preferredRank.has(b) ? preferredRank.get(b) : Number.MAX_SAFE_INTEGER;
    if (aRank !== bRank) {
      return aRank - bRank;
    }
    return a.localeCompare(b);
  });
}

async function main() {
  console.log('ailab: configuring openclaw...');

  console.log(`ailab: lemonade-server port detected: ${LEMONADE_PORT}`);
  const modelIds = probeDownloadedModels(LEMONADE.baseUrl);
  const downloadedIds = new Set(modelIds || []);

  let primaryModel = FALLBACK_MODEL;

  if (modelIds) {
    console.log(`ailab: lemonade found — ${modelIds.length} model(s): ${modelIds.join(', ')}`);
  } else {
    console.log('ailab: lemonade not reachable — pre-configuring with defaults');
    console.log('  (config will be ready once lemonade-server starts on the host)');
  }

  const preferredModel = choosePreferredModel(downloadedIds);
  if (preferredModel) {
    primaryModel = preferredModel;
  } else {
    if (modelIds !== null && !downloadedIds.has(FALLBACK_MODEL)) {
      const pullStarted = pullLemonadeModel(LEMONADE.baseUrl, FALLBACK_MODEL);
      if (pullStarted) {
        console.log(`ailab: requested lemonade download for ${FALLBACK_MODEL}`);
      } else {
        console.log(`ailab: could not request lemonade download for ${FALLBACK_MODEL}`);
      }
    }
    downloadedIds.add(FALLBACK_MODEL);
  }

  // Tell lemonade to load the primary model so it is ready when the user
  // opens openclaw for the first time.
  if (modelIds !== null) {
    console.log(`ailab: requesting lemonade load for ${primaryModel}...`);
    const loaded = loadLemonadeModel(LEMONADE.baseUrl, primaryModel);
    if (loaded) {
      console.log(`ailab: lemonade model ${primaryModel} loaded`);
    } else {
      console.log(`ailab: lemonade load request failed for ${primaryModel} (non-fatal)`);
    }
  }

  const normModels = sortModelsForConfig(downloadedIds).map(id => ({
    id,
    name:          id,
    reasoning:     false,
    input:         ['text'],
    cost:          { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 32768,
    maxTokens:     8192,
  }));

  // Read existing config so we can preserve the gateway section written by
  // openclaw onboard (it contains device auth and scope settings that must
  // survive across restarts).  We only own the models and agents sections.
  let existing = {};
  try {
    existing = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
  } catch {
    // No existing config — start fresh with a baseline gateway block.
    existing = {
      gateway: {
        mode: 'local',
        auth: { mode: 'token' },
      },
    };
  }

  const config = {
    ...existing,
    models: {
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
        workspace: WORKSPACE,
        sandbox:   { mode: 'off' },
        model:     { primary: `lemonade/${primaryModel}` },
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
  console.log('  Provider: lemonade');
  console.log(`  Lemonade → localhost:${LEMONADE_PORT}/api/v1 via OpenAI-compatible completions API (proxied from host)`);
  console.log('  Web UI → http://localhost:18789 (accessible on host)');
}

main().catch(err => {
  console.error(`ailab: setup_openclaw failed: ${err.message}`);
  process.exit(1);
});
