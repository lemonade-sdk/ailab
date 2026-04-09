import { useEffect, useRef, useState } from 'react';
import { LemonadeRecipe, Package, SSEEvent } from '../types';
import { getLemonadeRecipes, getPackages, importRecipeStream, installStream } from '../api/client';

interface Props {
  containerName: string;
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

export function InstallModal({ containerName, onClose, onDone }: Props) {
  const [packages, setPackages] = useState<Package[]>([]);
  const [selected, setSelected] = useState('');
  const [recipes, setRecipes] = useState<LemonadeRecipe[]>([]);
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
      const visible = pkgs.filter((p) => !['nullclaw', 'picoclaw'].includes(p.name));
      if (visible.length > 0) setSelected(visible[0].name);
    }).catch(console.error);
  }, []);

  // Fetch recipes whenever openclaw is selected
  useEffect(() => {
    if (selected !== 'openclaw') return;
    setRecipesLoading(true);
    setRecipesError('');
    getLemonadeRecipes()
      .then((r) => { setRecipes(r); setRecipesLoading(false); })
      .catch((e) => { setRecipesError(String(e)); setRecipesLoading(false); });
  }, [selected]);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [log]);

  const appendLog = (msg: string) => setLog((prev) => prev + msg + '\n');

  const handleInstall = async () => {
    if (!selected) return;
    setError('');
    setRunning(true);
    setLog('');
    let installFailed = false;

    try {
      // Phase 1: install the package
      await installStream(containerName, selected, (event: SSEEvent) => {
        if (event.type === 'log') appendLog(event.msg);
        else if (event.type === 'error') { setError(event.msg); installFailed = true; }
      });

      if (installFailed) { setDone(true); return; }

      // Phase 2: import recipe (openclaw only, when a recipe is selected)
      if (selected === 'openclaw' && selectedRecipe) {
        appendLog('');
        appendLog('--- Importing model recipe ---');
        await importRecipeStream(containerName, selectedRecipe, (event: SSEEvent) => {
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

  const visiblePackages = packages.filter((p) => !['nullclaw', 'picoclaw'].includes(p.name));

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className={`bg-slate-800 rounded-xl shadow-2xl w-full border border-slate-700 flex flex-col max-h-[90vh] ${selected === 'openclaw' ? 'max-w-lg' : 'max-w-md'}`}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <h2 className="text-white font-semibold text-lg">Install package — {containerName}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none">×</button>
        </div>

        <div className="overflow-y-auto flex-1 p-6 space-y-4">
          <div>
            <label className="block text-sm text-slate-300 mb-1">Package</label>
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              disabled={running}
              className="w-full bg-slate-700 text-white px-3 py-2 rounded-lg border border-slate-600 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
            >
              {visiblePackages.map((pkg) => (
                <option key={pkg.name} value={pkg.name}>
                  {pkg.name} — {pkg.description}
                </option>
              ))}
            </select>
          </div>

          {selected === 'openclaw' && (
            <div>
              <label className="block text-sm text-slate-300 mb-2">Model</label>
              {recipesLoading ? (
                <p className="text-sm text-slate-400">Loading available models…</p>
              ) : recipesError ? (
                <p className="text-sm text-amber-400">
                  Could not load model list — auto-detect will be used
                </p>
              ) : (
                <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
                  {/* Auto-detect option */}
                  <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${selectedRecipe === null ? 'border-indigo-500 bg-indigo-950/40' : 'border-slate-600 hover:border-slate-500'}`}>
                    <input
                      type="radio"
                      name="recipe"
                      checked={selectedRecipe === null}
                      onChange={() => setSelectedRecipe(null)}
                      disabled={running}
                      className="mt-0.5 accent-indigo-500"
                    />
                    <div>
                      <div className="text-white text-sm font-medium">Auto-detect</div>
                      <div className="text-slate-400 text-xs mt-0.5">
                        Use whichever model lemonade-server currently has loaded
                      </div>
                    </div>
                  </label>

                  {recipes.map((recipe) => {
                    const isSelected = selectedRecipe?._name === recipe._name;
                    const visibleLabels = (recipe.labels ?? []).filter((l) => VISIBLE_LABELS.has(l));
                    return (
                      <label
                        key={recipe._name}
                        className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${isSelected ? 'border-indigo-500 bg-indigo-950/40' : 'border-slate-600 hover:border-slate-500'}`}
                      >
                        <input
                          type="radio"
                          name="recipe"
                          checked={isSelected}
                          onChange={() => setSelectedRecipe(recipe)}
                          disabled={running}
                          className="mt-0.5 accent-indigo-500"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="text-white text-sm font-medium">{recipe._name}</div>
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
              className="bg-indigo-600 hover:bg-indigo-500 text-white px-5 py-2 rounded-lg text-sm font-medium"
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
                onClick={handleInstall}
                disabled={running || !selected}
                className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-5 py-2 rounded-lg text-sm font-medium"
              >
                {running ? 'Installing…' : 'Install'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
