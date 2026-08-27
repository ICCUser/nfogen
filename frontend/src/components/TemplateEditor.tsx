interface Props {
  value: string;
  onChange: (value: string) => void;
}

/** Editeur brut d'un template Jinja2 (.j2) pour une categorie. Pas de
 * coloration syntaxique : un textarea suffit pour ce volume de contenu, et
 * evite une dependance d'editeur de code supplementaire. */
export default function TemplateEditor({ value, onChange }: Props) {
  return (
    <div className="space-y-1">
      <textarea
        className="w-full rounded-md border border-line-strong bg-surface px-3 py-2 font-mono text-xs text-ink"
        rows={16}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="{{ raw_text }}"
        spellCheck={false}
      />
      <p className="text-xs text-ink-faint">
        Syntaxe Jinja2 (rendu sandboxé). Filtres disponibles : dotpad, colonpad, human_bin, human_dec, mmss.
        Fonction globale : banner(texte).
      </p>
    </div>
  );
}
