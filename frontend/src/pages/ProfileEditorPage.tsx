import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  deleteManagedProfile,
  exportManagedProfile,
  importManagedProfile,
  readManagedProfile,
  writeManagedProfile,
} from "../api/client";
import { ApiError, CATEGORIES } from "../api/types";
import type { Category, RulesDocument, TemplatesDocument } from "../api/types";
import CategoryRulesForm from "../components/rules/CategoryRulesForm";
import TemplateEditor from "../components/TemplateEditor";
import PreviewPanel from "../components/PreviewPanel";

interface Props {
  mode: "create" | "edit";
}

type Tab = "rules" | "templates" | "preview";

export default function ProfileEditorPage({ mode }: Props) {
  const params = useParams<{ name: string }>();
  const navigate = useNavigate();
  const importInputRef = useRef<HTMLInputElement>(null);

  const [name, setName] = useState(params.name ?? "");
  const [rules, setRules] = useState<RulesDocument>({});
  const [templates, setTemplates] = useState<TemplatesDocument>({});
  const [category, setCategory] = useState<Category>("video");
  const [tab, setTab] = useState<Tab>("rules");
  const [loading, setLoading] = useState(mode === "edit");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (mode !== "edit" || !params.name) return;
    (async () => {
      try {
        const data = await readManagedProfile(params.name!);
        setRules(data.rules);
        setTemplates(data.templates);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Profil introuvable.");
      } finally {
        setLoading(false);
      }
    })();
  }, [mode, params.name]);

  async function save() {
    if (!name.trim()) {
      setError("Le nom du profil est obligatoire.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await writeManagedProfile(name.trim(), rules, templates);
      setNotice("Profil enregistré.");
      if (mode === "create") navigate(`/profiles/${encodeURIComponent(name.trim())}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Erreur inattendue lors de l'enregistrement.");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!params.name) return;
    if (
      !confirm(
        `Supprimer la version personnalisée du profil '${params.name}' ? ` +
          `Si ce nom correspond à un profil livré avec nfogen (ex. c411), sa version d'origine sera restaurée.`,
      )
    )
      return;
    try {
      await deleteManagedProfile(params.name);
      navigate("/profils");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Erreur inattendue lors de la suppression.");
    }
  }

  async function exportZip() {
    if (!params.name) return;
    try {
      const blob = await exportManagedProfile(params.name);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${params.name}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Erreur inattendue lors de l'export.");
    }
  }

  async function importZip(file: File) {
    if (!name.trim()) {
      setError("Indiquez le nom du profil avant d'importer une archive.");
      return;
    }
    try {
      await importManagedProfile(name.trim(), file);
      const data = await readManagedProfile(name.trim());
      setRules(data.rules);
      setTemplates(data.templates);
      setNotice("Archive importée.");
      if (mode === "create") navigate(`/profiles/${encodeURIComponent(name.trim())}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Erreur inattendue lors de l'import.");
    }
  }

  if (loading) return <p className="text-sm text-ink-faint">Chargement…</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <label className="block text-sm font-medium text-ink-dim">
            Nom du profil
            <input
              className="mt-1 rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
              value={name}
              disabled={mode === "edit"}
              onChange={(e) => setName(e.target.value)}
              placeholder="ex. mon_tracker"
            />
          </label>
        </div>
        <div className="flex gap-2">
          {mode === "edit" && (
            <>
              <button
                type="button"
                onClick={exportZip}
                className="rounded-md border border-line-strong px-3 py-2 text-sm text-ink hover:bg-surface-2"
              >
                Exporter .zip
              </button>
              <button
                type="button"
                onClick={remove}
                className="rounded-md border border-crit px-3 py-2 text-sm text-crit hover:bg-crit-bg"
              >
                Supprimer
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => importInputRef.current?.click()}
            className="rounded-md border border-line-strong px-3 py-2 text-sm text-ink hover:bg-surface-2"
          >
            Importer .zip
          </button>
          <input
            ref={importInputRef}
            type="file"
            accept=".zip"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) importZip(file);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
          >
            {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-crit bg-crit-bg px-4 py-3 text-sm text-crit">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-md border border-good bg-good-bg px-4 py-3 text-sm text-good">
          {notice}
        </div>
      )}

      <div className="flex gap-1 border-b border-line">
        {CATEGORIES.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setCategory(c)}
            className={`px-3 py-2 font-mono text-sm font-medium ${
              category === c
                ? "border-b-2 border-accent text-ink"
                : "text-ink-faint hover:text-ink-dim"
            }`}
          >
            {c}
          </button>
        ))}
      </div>

      <div className="flex gap-1">
        {(["rules", "templates", "preview"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`rounded-md px-3 py-1.5 text-sm ${
              tab === t ? "bg-accent text-surface" : "bg-surface-2 text-ink-dim hover:bg-line"
            }`}
          >
            {t === "rules" ? "Règles" : t === "templates" ? "Template" : "Aperçu"}
          </button>
        ))}
      </div>

      <div className="rounded-md border border-line bg-surface p-4">
        {tab === "rules" && (
          <CategoryRulesForm
            rules={rules[category] ?? {}}
            onChange={(catRules) => setRules({ ...rules, [category]: catRules })}
          />
        )}
        {tab === "templates" && (
          <TemplateEditor
            value={templates[category] ?? ""}
            onChange={(value) => setTemplates({ ...templates, [category]: value })}
          />
        )}
        {tab === "preview" && mode === "edit" && params.name && (
          <PreviewPanel profile={params.name} category={category} />
        )}
        {tab === "preview" && mode === "create" && (
          <p className="text-sm text-ink-faint">Enregistrez d'abord le profil pour pouvoir le tester.</p>
        )}
      </div>
    </div>
  );
}
