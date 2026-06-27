import type { CategoryRules, Comparator, CrossCheck, Token, TokenLevel, TrackLanguageCheck } from "../../api/types";
import { KeyValueEditor, ListEditor } from "../ListEditor";
import AliasesField from "./AliasesField";

interface Props {
  rules: CategoryRules;
  onChange: (rules: CategoryRules) => void;
}

const LEVELS: TokenLevel[] = ["required", "recommended"];
const COMPARATORS: Comparator[] = ["int_equals", "codec_alias"];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      {children}
    </label>
  );
}

const inputCls = "mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm";

export default function CategoryRulesForm({ rules, onChange }: Props) {
  function patch(p: Partial<CategoryRules>) {
    onChange({ ...rules, ...p });
  }

  function patchNameProposal(p: { template?: string; language_aliases?: Record<string, string> }) {
    const merged = { ...rules.name_proposal, ...p };
    const hasTemplate = !!merged.template;
    const hasAliases = !!merged.language_aliases && Object.keys(merged.language_aliases).length > 0;
    patch({ name_proposal: hasTemplate || hasAliases ? merged : undefined });
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <Field label="Champ obligatoire (requires_field)">
          <input
            className={inputCls}
            value={rules.requires_field ?? ""}
            onChange={(e) => patch({ requires_field: e.target.value || undefined })}
            placeholder="ex. release_name"
          />
        </Field>
        <Field label="Modèle de nom de fichier (filename_template)">
          <input
            className={inputCls}
            value={rules.filename_template ?? ""}
            onChange={(e) => patch({ filename_template: e.target.value || undefined })}
            placeholder="ex. {release_name}.nfo"
          />
        </Field>
        <Field label="Description (doc)">
          <input
            className={inputCls}
            value={rules.doc ?? ""}
            onChange={(e) => patch({ doc: e.target.value || undefined })}
          />
        </Field>
        <Field label="Exemple conforme (example)">
          <input
            className={inputCls}
            value={rules.example ?? ""}
            onChange={(e) => patch({ example: e.target.value || undefined })}
          />
        </Field>
      </div>

      <div className="flex gap-6">
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={rules.forbid_spaces ?? false}
            onChange={(e) => patch({ forbid_spaces: e.target.checked || undefined })}
          />
          Interdire les espaces
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={rules.forbid_non_ascii ?? false}
            onChange={(e) => patch({ forbid_non_ascii: e.target.checked || undefined })}
          />
          Interdire les accents/non-ASCII
        </label>
      </div>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">Tokens (motifs de nommage)</h3>
        <ListEditor<Token>
          items={rules.tokens ?? []}
          onChange={(tokens) => patch({ tokens: tokens.length ? tokens : undefined })}
          newItem={() => ({ name: "", pattern: "" })}
          addLabel="Ajouter un token"
          renderRow={(token, update) => (
            <div className="grid grid-cols-2 gap-2">
              <input
                className="rounded border border-slate-300 px-2 py-1 text-sm"
                placeholder="nom"
                value={token.name}
                onChange={(e) => update({ name: e.target.value })}
              />
              <input
                className="rounded border border-slate-300 px-2 py-1 font-mono text-xs"
                placeholder="regex Python (?P<...>...)"
                value={token.pattern}
                onChange={(e) => update({ pattern: e.target.value })}
              />
              <select
                className="rounded border border-slate-300 px-2 py-1 text-sm"
                value={token.level ?? ""}
                onChange={(e) => update({ level: (e.target.value || undefined) as TokenLevel | undefined })}
              >
                <option value="">(membre d'un groupe uniquement)</option>
                {LEVELS.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
              <input
                className="rounded border border-slate-300 px-2 py-1 text-sm"
                placeholder="groupe (optionnel)"
                value={token.group ?? ""}
                onChange={(e) => update({ group: e.target.value || undefined })}
              />
              <input
                className="col-span-2 rounded border border-slate-300 px-2 py-1 text-sm"
                placeholder="message si 'required' et absent"
                value={token.error ?? ""}
                onChange={(e) => update({ error: e.target.value || undefined })}
              />
              <input
                className="col-span-2 rounded border border-slate-300 px-2 py-1 text-sm"
                placeholder="message si 'recommended' et absent"
                value={token.warning ?? ""}
                onChange={(e) => update({ warning: e.target.value || undefined })}
              />
            </div>
          )}
        />
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">
          Groupes alternatifs (require_one_of_groups)
        </h3>
        <p className="mb-2 text-xs text-slate-500">
          Pour chaque groupe, au moins un token membre doit matcher — sinon le message associé bloque la
          génération.
        </p>
        <KeyValueEditor
          value={rules.require_one_of_groups ?? {}}
          onChange={(v) => patch({ require_one_of_groups: Object.keys(v).length ? v : undefined })}
          keyPlaceholder="nom du groupe"
          valuePlaceholder="message si aucun token du groupe ne matche"
        />
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">
          Croisements avec le fichier réel (cross_checks)
        </h3>
        <ListEditor<CrossCheck>
          items={rules.cross_checks ?? []}
          onChange={(v) => patch({ cross_checks: v.length ? v : undefined })}
          newItem={() => ({ capture: "", metadata_field: "", comparator: "int_equals", message: "" })}
          addLabel="Ajouter un croisement"
          renderRow={(check, update) => (
            <div className="space-y-1">
              <div className="grid grid-cols-3 gap-2">
                <input
                  className="rounded border border-slate-300 px-2 py-1 text-sm"
                  placeholder="capture (groupe nommé d'un token)"
                  value={check.capture}
                  onChange={(e) => update({ capture: e.target.value })}
                />
                <input
                  className="rounded border border-slate-300 px-2 py-1 text-sm"
                  placeholder="metadata_field (ex. video_height)"
                  value={check.metadata_field}
                  onChange={(e) => update({ metadata_field: e.target.value })}
                />
                <select
                  className="rounded border border-slate-300 px-2 py-1 text-sm"
                  value={check.comparator}
                  onChange={(e) => update({ comparator: e.target.value as Comparator })}
                >
                  {COMPARATORS.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>
              <input
                className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                placeholder="message ({capture} / {actual} disponibles)"
                value={check.message}
                onChange={(e) => update({ message: e.target.value })}
              />
              {check.comparator === "codec_alias" && (
                <AliasesField value={check.aliases} onChange={(aliases) => update({ aliases })} />
              )}
            </div>
          )}
        />
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">
          Vérification des langues de piste (track_language_checks)
        </h3>
        <ListEditor<TrackLanguageCheck>
          items={rules.track_language_checks ?? []}
          onChange={(v) => patch({ track_language_checks: v.length ? v : undefined })}
          newItem={() => ({ metadata_field: "", label: "" })}
          addLabel="Ajouter une vérification"
          renderRow={(check, update) => (
            <div className="grid grid-cols-2 gap-2">
              <input
                className="rounded border border-slate-300 px-2 py-1 text-sm"
                placeholder="metadata_field (ex. audio_languages)"
                value={check.metadata_field}
                onChange={(e) => update({ metadata_field: e.target.value })}
              />
              <input
                className="rounded border border-slate-300 px-2 py-1 text-sm"
                placeholder="label (ex. Piste audio)"
                value={check.label}
                onChange={(e) => update({ label: e.target.value })}
              />
              <input
                className="rounded border border-slate-300 px-2 py-1 text-sm"
                placeholder="hint_capture (optionnel)"
                value={check.hint_capture ?? ""}
                onChange={(e) => update({ hint_capture: e.target.value || undefined })}
              />
              <input
                className="rounded border border-slate-300 px-2 py-1 text-sm"
                placeholder="message si liste vide (optionnel)"
                value={check.warn_if_empty ?? ""}
                onChange={(e) => update({ warn_if_empty: e.target.value || undefined })}
              />
            </div>
          )}
        />
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">
          Proposition automatique de nom (name_proposal)
        </h3>
        <p className="mb-2 text-xs text-slate-500">
          Suggère un <code>release_name</code> à partir des noms de fichiers sélectionnés (page « Générer »),
          sans upload. Champs disponibles dans le modèle :{" "}
          <code>{"{title} {identifier} {language} {resolution} {video_codec} {audio} {source} {team}"}</code>.
        </p>
        <Field label="Modèle (template)">
          <input
            className={inputCls}
            value={rules.name_proposal?.template ?? ""}
            onChange={(e) => patchNameProposal({ template: e.target.value || undefined })}
            placeholder="ex. {title}.{identifier}.{language}.{resolution}p.{source}.{audio}.{video_codec}-{team}"
          />
        </Field>
        <div className="mt-3">
          <p className="mb-1 text-xs font-medium text-slate-700">
            Correspondance des tags de langue (language_aliases) — ex. clé <code>FR+JA</code>, valeur{" "}
            <code>MULTI.VFF</code>
          </p>
          <KeyValueEditor
            value={rules.name_proposal?.language_aliases ?? {}}
            onChange={(v) => patchNameProposal({ language_aliases: Object.keys(v).length ? v : undefined })}
            keyPlaceholder="tag source (ex. FR+JA)"
            valuePlaceholder="tag normalisé (ex. MULTI.VFF)"
          />
        </div>
      </section>
    </div>
  );
}
