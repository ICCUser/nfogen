import { useState } from "react";

interface Props {
  value?: Record<string, string[]>;
  onChange: (value?: Record<string, string[]>) => void;
}

/** Champ JSON libre pour `cross_checks[].aliases` (dict de listes) : forme
 * trop ponctuelle pour justifier un editeur dedie, un textarea JSON suffit. */
export default function AliasesField({ value, onChange }: Props) {
  const [text, setText] = useState(() => JSON.stringify(value ?? {}));
  const [error, setError] = useState<string | null>(null);

  return (
    <div>
      <label className="block text-xs font-medium text-ink-faint">
        Alias (JSON, optionnel — ex. {'{"x264":["avc"]}'})
      </label>
      <textarea
        className="mt-1 w-full rounded border border-line-strong bg-surface px-2 py-1 font-mono text-xs text-ink"
        rows={2}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const parsed = e.target.value.trim() ? JSON.parse(e.target.value) : {};
            setError(null);
            onChange(Object.keys(parsed).length ? parsed : undefined);
          } catch {
            setError("JSON invalide");
          }
        }}
      />
      {error && <p className="text-xs text-crit">{error}</p>}
    </div>
  );
}
