import { useState } from "react";
import { getBaseUrl, getToken, setBaseUrl, setToken } from "../api/settings";

export default function SettingsPage() {
  const [baseUrl, setBaseUrlState] = useState(getBaseUrl());
  const [token, setTokenState] = useState(getToken());
  const [saved, setSaved] = useState(false);

  function save() {
    setBaseUrl(baseUrl.trim());
    setToken(token.trim());
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }

  return (
    <div className="max-w-lg space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">Réglages de connexion</h1>
      <p className="text-sm text-slate-600">
        Stockés uniquement dans ce navigateur (localStorage). Le token n'est requis que si
        l'API nfogen a été démarrée avec <code className="rounded bg-slate-100 px-1">NFOGEN_API_TOKEN</code>.
      </p>

      <label className="block text-sm font-medium text-slate-700">
        URL de base de l'API
        <input
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          value={baseUrl}
          onChange={(e) => setBaseUrlState(e.target.value)}
          placeholder="/api"
        />
      </label>

      <label className="block text-sm font-medium text-slate-700">
        Token API
        <input
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          type="password"
          value={token}
          onChange={(e) => setTokenState(e.target.value)}
          placeholder="(laisser vide si NFOGEN_API_TOKEN n'est pas définie)"
        />
      </label>

      <button
        type="button"
        onClick={save}
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
      >
        Enregistrer
      </button>
      {saved && <span className="ml-3 text-sm text-emerald-600">Enregistré.</span>}
    </div>
  );
}
