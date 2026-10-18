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
import Button from "../components/Button";
import ConfirmButton from "../components/ConfirmButton";
import Tabs from "../components/Tabs";

interface Props {
  mode: "create" | "edit";
}

type Tab = "rules" | "templates" | "preview";

const TABS: readonly { value: Tab; label: string }[] = [
  { value: "rules", label: "Règles" },
  { value: "templates", label: "Template" },
  { value: "preview", label: "Aperçu" },
];

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
    // Confirme en amont par le ConfirmButton "Supprimer" (audit front
    // 2026-10-14, lot 4 : plus de window.confirm()).
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
              <Button
                variant="secondary"
                onClick={exportZip}
              >
                Exporter .zip
              </Button>
              <ConfirmButton
                variant="danger-secondary"
                question="Supprimer la version personnalisée ? Un profil livré avec nfogen (ex. c411) retrouve sa version d'origine."
                confirmLabel="Oui, supprimer"
                onConfirm={remove}
              >
                Supprimer
              </ConfirmButton>
            </>
          )}
          <Button
            variant="secondary"
            onClick={() => importInputRef.current?.click()}
          >
            Importer .zip
          </Button>
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
          <Button
            variant="primary"
            onClick={save}
            disabled={saving}
          >
            {saving ? "Enregistrement…" : "Enregistrer"}
          </Button>
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-md border border-crit bg-crit-bg px-4 py-3 text-sm text-crit">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="rounded-md border border-good bg-good-bg px-4 py-3 text-sm text-good">
          {notice}
        </div>
      )}

      <Tabs
        label="Catégorie"
        idPrefix="category-tab"
        controls="profile-editor-panel"
        items={CATEGORIES.map((c) => ({ value: c, label: c }))}
        value={category}
        onChange={setCategory}
        mono
      />

      <Tabs
        label="Section"
        idPrefix="section-tab"
        controls="profile-editor-panel"
        variant="segmented"
        items={TABS}
        value={tab}
        onChange={setTab}
      />

      <div
        id="profile-editor-panel"
        role="tabpanel"
        aria-labelledby={`category-tab-${category} section-tab-${tab}`}
        className="rounded-md border border-line bg-surface p-4"
      >
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
