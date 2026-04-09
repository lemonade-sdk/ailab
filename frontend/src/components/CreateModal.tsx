import { useState, useEffect, useRef } from 'react';
import { LemonadeRecipe, Package, SSEEvent, SystemUser } from '../types';
import { createContainerStream, getLemonadeDownloadedModels, getLemonadeRecipes, getPackages, getUsers, importRecipeStream } from '../api/client';

interface Props {
  onClose: () => void;
  onDone: () => void;
}

const VISIBLE_LABELS = new Set(['vision', 'tool-calling']);

function RecipeTag({ label }: { label: string }) {
  const colours: Record<string, string> = {
    vision: 'bg-violet-900 text-violet-300',
    'tool-calling': 'bg-blue-900 text-blue-300',
  };
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${colours[label] ?? 'bg-slate-700 text-slate-300'}`}>
      {label}
    </span>
  );
}

export function CreateModal({ onClose, onDone }: Props) {
  const [name, setName] = useState('');
  const [packages, setPackages] = useState<Package[]>([]);
  const [selectedPackage, setSelectedPackage] = useState<string>('');
  const [users, setUsers] = useState<SystemUser[]>([]);
  const [selectedUser, setSelectedUser] = useState<string>('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [extraPorts, setExtraPorts] = useState<Array<{ host: string; container: string }>>([]);
  const [recipes, setRecipes] = useState<LemonadeRecipe[]>([]);
  const [downloadedModels, setDownloadedModels] = useState<Set<string>>(new Set());
  const [recipesLoading, setRecipesLoading] = useState(false);
  const [recipesError, setRecipesError] = useState('');
  // null = auto-detect (no recipe selected)
  const [selectedRecipe, setSelectedRecipe] = useState<LemonadeRecipe | null>(null);
  const [log, setLog] = useState('');
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const logRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    getPackages().then((pkgs) => {
      setPackages(pkgs);
    }).catch(console.error);

    getUsers().then((us) => {
      setUsers(us);
      if (us.length === 1) setSelectedUser(us[0].username);
    }).catch(console.error);
  }, []);

  // Fetch recipes whenever openclaw is selected
  useEffect(() => {
    if (selectedPackage !== 'openclaw') return;
    setRecipesLoading(true);
    setRecipesError('');
    Promise.all([getLemonadeRecipes(), getLemonadeDownloadedModels()])
      .then(([r, downloaded]) => {
        setRecipes(r);
        setDownloadedModels(new Set(downloaded));
        setRecipesLoading(false);
      })
      .catch((e) => { setRecipesError(String(e)); setRecipesLoading(false); });
  }, [selectedPackage]);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [log]);

  const appendLog = (msg: string) => setLog((prev) => prev + msg + '\n');

  const addPortRow = () => setExtraPorts((prev) => [...prev, { host: '', container: '' }]);
  const removePortRow = (i: number) => setExtraPorts((prev) => prev.filter((_, idx) => idx !== i));
  const updatePort = (i: number, field: 'host' | 'container', value: string) => {
    setExtraPorts((prev) => prev.map((p, idx) => (idx === i ? { ...p, [field]: value } : p)));
  };

  const handleSubmit = async () => {
    if (!name.trim()) { setError('Name is required.'); return; }
    setError('');
    setRunning(true);
    setLog('');

    const pkgs = selectedPackage ? [selectedPackage] : [];
    const ports = extraPorts
      .filter((p) => p.host && p.container)
      .map((p) => ({ host_port: parseInt(p.host), container_port: parseInt(p.container) }));

    let createFailed = false;

    try {
      // Phase 1: create container (+ install package)
      await createContainerStream(name.trim(), pkgs, ports, (event: SSEEvent) => {
        if (event.type === 'log') appendLog(event.msg);
        else if (event.type === 'done') { /* proceed */ }
        else if (event.type === 'error') { setError(event.msg); createFailed = true; }
      }, selectedUser || undefined);

      if (createFailed) { setDone(true); return; }

      // Phase 2: import recipe (openclaw only, when a recipe is selected)
      if (selectedPackage === 'openclaw' && selectedRecipe) {
        appendLog('');
        appendLog('--- Importing model recipe ---');
        await importRecipeStream(name.trim(), selectedRecipe, (event: SSEEvent) => {
          if (event.type === 'log') appendLog(event.msg);
          else if (event.type === 'error') setError(event.msg);
        });
      }

      setDone(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 rounded-xl shadow-2xl w-full max-w-lg border border-slate-700 flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <h2 className="text-white font-semibold text-lg">New Container</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none">×</button>
        </div>

        <div className="overflow-y-auto p-6 space-y-5 flex-1">
          <div>
            <label className="block text-sm text-slate-300 mb-1">Container name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={running}
              placeholder="mybox"
              className="w-full bg-slate-700 text-white px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:ring-2 focus:ring-lemon-500 text-sm disabled:opacity-50"
            />
          </div>

          {users.length > 1 && (
            <div>
              <label className="block text-sm text-slate-300 mb-1">Map user into container</label>
              <select
                value={selectedUser}
                onChange={(e) => setSelectedUser(e.target.value)}
                disabled={running}
                className="w-full bg-slate-700 text-white px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:ring-2 focus:ring-lemon-500 text-sm disabled:opacity-50"
              >
                <option value="">— select user —</option>
                {users.map((u) => (
                  <option key={u.username} value={u.username}>
                    {u.username} (uid {u.uid}) — {u.home}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="block text-sm text-slate-300 mb-1">Install package</label>
            <select
              value={selectedPackage}
              onChange={(e) => setSelectedPackage(e.target.value)}
              disabled={running}
              className="w-full bg-slate-700 text-white px-3 py-2 rounded-lg border border-slate-600 focus:outline-none focus:ring-2 focus:ring-lemon-500 text-sm disabled:opacity-50"
            >
              <option value="">— none (bare container) —</option>
              {packages.filter((pkg) => !['nullclaw', 'picoclaw'].includes(pkg.name)).map((pkg) => (
                <option key={pkg.name} value={pkg.name}>
                  {pkg.name} — {pkg.description}
                </option>
              ))}
            </select>
          </div>

          {selectedPackage === 'openclaw' && (
            <div>
              <label className="block text-sm text-slate-300 mb-2">Model</label>
              {recipesLoading ? (
                <p className="text-sm text-slate-400">Loading available models…</p>
              ) : recipesError ? (
                <p className="text-sm text-amber-400">
                  Could not load model list — auto-detect will be used
                </p>
              ) : (
                <div className="space-y-1.5 max-h-56 overflow-y-auto pr-1">
                  <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${selectedRecipe === null ? 'border-lemon-500/60 bg-lemon-500/10' : 'border-slate-600 hover:border-slate-500'}`}>
                    <input type="radio" name="recipe" checked={selectedRecipe === null} onChange={() => setSelectedRecipe(null)} disabled={running} className="sr-only" />
                    <div className={`mt-0.5 w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 transition-colors ${selectedRecipe === null ? 'border-lemon-500' : 'border-slate-500'}`}>
                      {selectedRecipe === null && <div className="w-2 h-2 rounded-full bg-lemon-500" />}
                    </div>
                    <div>
                      <div className="text-white text-sm font-medium">Auto-detect</div>
                      <div className="text-slate-400 text-xs mt-0.5">
                        Use whichever model lemonade-server currently has loaded
                      </div>
                    </div>
                  </label>

                  {recipes.map((recipe) => {
                    const isSelected = selectedRecipe?._name === recipe._name;
                    const isDownloaded = recipe.model_name ? downloadedModels.has(recipe.model_name) : false;
                    const visibleLabels = (recipe.labels ?? []).filter((l) => VISIBLE_LABELS.has(l));
                    return (
                      <label
                        key={recipe._name}
                        className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${isSelected ? 'border-lemon-500/60 bg-lemon-500/10' : 'border-slate-600 hover:border-slate-500'}`}
                      >
                        <input type="radio" name="recipe" checked={isSelected} onChange={() => setSelectedRecipe(recipe)} disabled={running} className="sr-only" />
                        <div className={`mt-0.5 w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 transition-colors ${isSelected ? 'border-lemon-500' : 'border-slate-500'}`}>
                          {isSelected && <div className="w-2 h-2 rounded-full bg-lemon-500" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-white text-sm font-medium">{recipe._name}</span>
                            {isDownloaded && (
                              <span className="text-xs px-1.5 py-0.5 rounded bg-teal-900 text-teal-300 font-medium">
                                downloaded
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 mt-1 flex-wrap">
                            {recipe.size != null && (
                              <span className="text-slate-400 text-xs">{recipe.size} GB</span>
                            )}
                            {visibleLabels.map((label) => (
                              <RecipeTag key={label} label={label} />
                            ))}
                          </div>
                        </div>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          <div className="border-t border-slate-700 pt-2">
            <button
              onClick={() => setShowAdvanced((v) => !v)}
              className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              <svg className={`w-3 h-3 transition-transform ${showAdvanced ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
              Advanced
            </button>

            {showAdvanced && (
              <div className="mt-3">
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm text-slate-300">Extra ports (HOST:CONTAINER)</label>
                  <button
                    onClick={addPortRow}
                    disabled={running}
                    className="text-xs text-lemon-500 hover:text-lemon-400 disabled:opacity-50"
                  >
                    + Add port
                  </button>
                </div>
                {extraPorts.map((p, i) => (
                  <div key={i} className="flex gap-2 mb-2">
                    <input
                      value={p.host}
                      onChange={(e) => updatePort(i, 'host', e.target.value)}
                      placeholder="Host port"
                      className="flex-1 bg-slate-700 text-white px-3 py-1.5 rounded border border-slate-600 text-sm focus:outline-none focus:ring-1 focus:ring-lemon-500"
                    />
                    <span className="text-slate-500 self-center">:</span>
                    <input
                      value={p.container}
                      onChange={(e) => updatePort(i, 'container', e.target.value)}
                      placeholder="Container port"
                      className="flex-1 bg-slate-700 text-white px-3 py-1.5 rounded border border-slate-600 text-sm focus:outline-none focus:ring-1 focus:ring-lemon-500"
                    />
                    <button onClick={() => removePortRow(i)} className="text-slate-500 hover:text-red-400 px-1">✕</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {log && (
            <div>
              <label className="block text-sm text-slate-400 mb-1">Output</label>
              <textarea
                ref={logRef}
                readOnly
                value={log}
                className="w-full h-40 bg-slate-900 text-green-400 text-xs font-mono p-3 rounded border border-slate-700 resize-none"
              />
            </div>
          )}

          {error && <p className="text-red-400 text-sm">{error}</p>}
        </div>

        <div className="px-6 py-4 border-t border-slate-700 flex justify-end gap-3">
          {done ? (
            <button
              onClick={onDone}
              className="bg-lemon-500 hover:bg-lemon-400 text-slate-950 font-semibold px-5 py-2 rounded-lg text-sm"
            >
              Done
            </button>
          ) : (
            <>
              <button
                onClick={onClose}
                disabled={running}
                className="text-slate-400 hover:text-white px-4 py-2 text-sm disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={running || !name.trim()}
                className="bg-lemon-500 hover:bg-lemon-400 disabled:opacity-50 disabled:cursor-not-allowed text-slate-950 font-semibold px-5 py-2 rounded-lg text-sm"
              >
                {running ? 'Creating…' : 'Create'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
