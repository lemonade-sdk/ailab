import { useEffect, useRef, useState } from 'react';
import { LemonadeRecipe, SSEEvent } from '../types';
import { getLemonadeDownloadedModels, getLemonadeRecipes, importRecipeStream } from '../api/client';

interface Props {
  containerName: string;
  /** Currently configured model, e.g. "lemonade/user.Qwen3-8B-GGUF" */
  currentModel: string | null;
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

/** Strip "lemonade/" and "user." prefixes to get the bare recipe name. */
function recipeNameFromModel(model: string): string {
  return model.replace(/^lemonade\//, '').replace(/^user\./, '');
}

export function ChangeModelModal({ containerName, currentModel, onClose, onDone }: Props) {
  const [recipes, setRecipes] = useState<LemonadeRecipe[]>([]);
  const [downloadedModels, setDownloadedModels] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState('');
  const [selectedRecipe, setSelectedRecipe] = useState<LemonadeRecipe | null>(null);
  const [log, setLog] = useState('');
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const logRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    Promise.all([
      getLemonadeRecipes(),
      getLemonadeDownloadedModels(),
    ])
      .then(([r, downloaded]) => {
        setRecipes(r);
        setDownloadedModels(new Set(downloaded));
        // Pre-select the recipe that matches the current model.
        if (currentModel) {
          const bare = recipeNameFromModel(currentModel);
          const match = r.find((rec) => rec._name === bare || rec.model_name === `user.${bare}`);
          if (match) setSelectedRecipe(match);
        }
        setLoading(false);
      })
      .catch((e) => { setFetchError(String(e)); setLoading(false); });
  }, [currentModel]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  const handleApply = async () => {
    if (!selectedRecipe) return;
    setError('');
    setRunning(true);
    setLog('');
    try {
      await importRecipeStream(containerName, selectedRecipe, (event: SSEEvent) => {
        if (event.type === 'log') setLog((prev) => prev + event.msg + '\n');
        else if (event.type === 'error') setError(event.msg);
      });
      setDone(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  };

  const currentBare = currentModel ? recipeNameFromModel(currentModel) : null;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 rounded-xl shadow-2xl w-full max-w-lg border border-slate-700 flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <div>
            <h2 className="text-white font-semibold text-lg">Change Model — {containerName}</h2>
            {currentBare && (
              <p className="text-slate-400 text-xs mt-0.5">Current: {currentBare}</p>
            )}
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none">×</button>
        </div>

        <div className="overflow-y-auto flex-1 p-6 space-y-4">
          {loading ? (
            <p className="text-sm text-slate-400">Loading available models…</p>
          ) : fetchError ? (
            <p className="text-sm text-red-400">Failed to load models: {fetchError}</p>
          ) : (
            <div className="space-y-1.5 max-h-96 overflow-y-auto pr-1">
              {recipes.map((recipe) => {
                const isSelected = selectedRecipe?._name === recipe._name;
                const isCurrent = recipe._name === currentBare;
                const isDownloaded = recipe.model_name ? downloadedModels.has(recipe.model_name) : false;
                const visibleLabels = (recipe.labels ?? []).filter((l) => VISIBLE_LABELS.has(l));
                return (
                  <label
                    key={recipe._name}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${isSelected ? 'border-lemon-500/60 bg-lemon-500/8' : 'border-slate-600 hover:border-slate-500'}`}
                  >
                    <input
                      type="radio"
                      name="recipe"
                      checked={isSelected}
                      onChange={() => setSelectedRecipe(recipe)}
                      disabled={running}
                      className="mt-0.5 accent-lemon-500"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-white text-sm font-medium">{recipe._name}</span>
                        {isCurrent && (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-green-900 text-green-300 font-medium">
                            current
                          </span>
                        )}
                        {isDownloaded && !isCurrent && (
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
                onClick={handleApply}
                disabled={running || !selectedRecipe}
                className="bg-lemon-500 hover:bg-lemon-400 disabled:opacity-50 disabled:cursor-not-allowed text-slate-950 font-semibold px-5 py-2 rounded-lg text-sm"
              >
                {running ? 'Applying…' : 'Apply'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
