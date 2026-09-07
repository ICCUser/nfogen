# Enrichissement du template d'upload + charte graphique nfogen — Design

## Contexte

Le template livre par nfogen ([nfogen/profiles/c411/templates/upload_description.j2](../../../nfogen/profiles/c411/templates/upload_description.j2))
a ete enrichi une premiere fois le 2026-09-07 (date/duree/classification/
studio, langues audio/sous-titres, taille/team). L'utilisateur a ensuite
partage un exemple de description **auto-generee par C411 lui-meme**
(Lucifer S05) qui va plus loin sur trois points : Pays/Createur(s)/Note
TMDB/lien IMDB, un tableau detaille par piste audio/sous-titres (drapeaux,
canaux, codec, bitrate), et des bannieres visuelles a la place des `[h2]`
texte.

Les bannieres de l'exemple C411 appartiennent a un autre utilisateur
(djoontah), hebergees sur c411.org — non reutilisables telles quelles
(voir discussion prealable). Ce design definit une charte graphique nfogen
propre, plus l'ajout des donnees manquantes.

## Objectif

1. Ajouter Pays / Createur(s) (series) / Note TMDB / lien IMDB au template,
   via un nouvel appel a l'API TMDB (ces champs sont absents de Radarr/
   Sonarr, confirme par des dumps reels).
2. Remplacer les separateurs `[h2]...[/h2]` par des bannieres image aux
   couleurs reelles de l'appli nfogen (`#141d19` / `#6bc9b3` / `#0e1512`),
   avec un credit `nfogen.nfo` en bas — assets statiques, generes une fois,
   commites dans le repo et servis via `raw.githubusercontent.com`.
3. Remplacer la liste simple de langues audio/sous-titres par un tableau
   BBCode par piste (drapeau, langue, canaux, codec, debit, sample rate /
   type FORCED-FULL pour les sous-titres).
4. Deplacer le panneau "Configuration globale" (Sonarr/Radarr/qBittorrent/
   staging/mappings) de `LibraryPage` vers `SettingsPage` (retour
   utilisateur : ces reglages ne sont pas lies a un profil de tracker, ils
   n'ont pas leur place sur la page de bibliotheque) et y ajouter le champ
   "Cle API TMDB".

## Contraintes globales

- Toute nouvelle donnee (TMDB ou MediaInfo) reste **optionnelle** : son
  absence ne bloque jamais la generation de la description ni l'envoi du
  brouillon (meme principe que le reste du template existant — une ligne
  disparait simplement si la donnee manque).
- Aucune regression sur le flux d'envoi existant (`send_to_tracker`) :
  l'appel TMDB est un enrichissement, jamais une dependance dure.
- La cle API TMDB est **globale** (comme Sonarr/Radarr/qBittorrent), pas
  namespacee par profil de tracker.
- Les bannieres sont des **assets statiques pre-generes**, pas generees a
  la volee a chaque upload (pas de nouvelle dependance runtime pour
  nfogen lui-meme).
- Repo GitHub de reference pour les URLs `raw.githubusercontent.com` :
  `ICCUser/nfogen`, branche `main`.

## Architecture — vue d'ensemble

Quatre morceaux independants, livrables et testables separement :

- **A. Migration de la config globale** vers `SettingsPage` + champ TMDB.
- **B. Client TMDB** (`nfogen/tmdb_client.py`), nouveau module.
- **C. Extraction MediaInfo par piste** (`nfogen/extract.py`) + mapping
  langue→drapeau (`nfogen/languages.py`, nouveau module).
- **D. Assets bannieres** (script de generation one-shot + fichiers
  commites) et **refonte du template** (`upload_description.j2`).

```
send_to_tracker()
  ├─ Radarr/Sonarr get_*_details()   (existant : overview/genres/cast/...)
  ├─ TMDB client (NOUVEAU, best-effort)  → country, creators, tmdb_rating
  ├─ extract.extract_video_metadata() (etendu) → audio_tracks, subtitle_tracks
  └─ render_upload_description(ctx)
       └─ upload_description.j2 (refondu : bannieres, tableau langues, TMDB)
```

## A. Migration config globale → SettingsPage

- **Retirer** de `LibraryPage.tsx` : le panneau "Configuration globale"
  entier (state `showGlobalConfigForm`/`globalConfigSaving`/
  `globalConfigSaved`/`globalConfigError`, `handleSaveGlobalConfig`, JSX
  associe) — ajoute le 2026-09-07, direction confirmee par l'utilisateur
  d'etre deplacee plutot que dupliquee.
- **Ajouter** a `SettingsPage.tsx` un panneau equivalent (meme
  comportement de repli/deploi automatique si Sonarr et Radarr sont tous
  les deux non configures), avec en plus un champ "Cle API TMDB"
  (`type="password"`, meme pattern que les autres cles).
- Le panneau garde le meme profil actif via `useProfile()` (contexte
  global deja utilise partout dans l'appli, y compris hors LibraryPage)
  pour l'appel `gapscanConfigWrite(fields, profile)` — le backend ignore
  deja `profile` pour ces champs, ce n'est qu'un parametre technique de
  l'endpoint.
- `LibraryPage` garde uniquement le panneau "Configuration du profil"
  (tracker_base_url/tracker_api_key/tracker_announce_url), qui lui reste
  lie au profil actif affiche sur cette page.

**Backend** (`nfogen/gapscan_config_store.py`, `nfogen/api.py`) :
- `write()` gagne `tmdb_api_key: Optional[str]`, ajoute a
  `top_level_updates` (comme `qbittorrent_verify_ssl`).
- Nouvelle fonction `effective_tmdb_api_key() -> Optional[str]` (meme
  pattern `_resolve(...)` que les autres cles : config store, sinon
  variable d'environnement `NFOGEN_TMDB_API_KEY`).
- `status()`/`GapscanConfig` gagnent `tmdb_configured: bool` (jamais la
  cle elle-meme, meme principe que `tracker_configured`).
- `GapscanConfigWriteRequest` gagne `tmdb_api_key: Optional[str] = None`.

## B. Client TMDB (`nfogen/tmdb_client.py`, nouveau)

Nouveau module, calque sur `radarr_client.py`/`sonarr_client.py` (meme
style : dataclass de resultat, exception dediee, client HTTP `httpx`).

```python
class TMDBError(Exception): ...

@dataclass
class TMDBExtraDetails:
    country: Optional[str] = None          # premier pays de production
    vote_average: Optional[float] = None    # note /10, arrondie a 1 decimale
    creators: list[str] = field(default_factory=list)  # series uniquement

class TMDBClient:
    def __init__(self, api_key: str, *, http_client: Optional[httpx.Client] = None): ...
    def get_movie_extra(self, tmdb_id: int) -> TMDBExtraDetails: ...
    def get_series_extra(self, tmdb_id: int) -> TMDBExtraDetails: ...
```

- Endpoints : `GET https://api.themoviedb.org/3/movie/{id}?api_key=...`
  et `GET https://api.themoviedb.org/3/tv/{id}?api_key=...` (auth v3 par
  parametre de requete, la plus simple — pas besoin du token v4 Bearer).
- `country` : `production_countries[0].name` (film) ou
  `production_countries[0].name` / a defaut `origin_country[0]` (serie),
  `None` si absent.
- `creators` : `created_by[].name` (serie uniquement — le film n'a pas ce
  champ, `TMDBExtraDetails.creators` reste vide pour un film).
- `vote_average` : `round(vote_average, 1)` si present et non nul (TMDB
  renvoie `0` pour un titre jamais note — traite comme absent).
- Toute erreur HTTP/reseau/JSON leve `TMDBError` — **charge a
  l'appelant** (`send_to_tracker`) de l'attraper et de continuer sans ces
  champs, jamais au client de degrader silencieusement (meme principe
  que les autres clients du projet : le client leve, l'appelant decide).

**Integration dans `upload_prep.send_to_tracker()`** :
```python
country = creators = tmdb_rating = None
tmdb_api_key = gapscan_config_store.effective_tmdb_api_key()
if tmdb_api_key and tmdb_id:
    try:
        tmdb_client = TMDBClient(tmdb_api_key)
        extra = (tmdb_client.get_movie_extra(int(tmdb_id)) if media_type == "movie"
                 else tmdb_client.get_series_extra(int(tmdb_id)))
        country, tmdb_rating = extra.country, extra.vote_average
        creators = extra.creators
    except TMDBError:
        pass  # best-effort : la description se genere sans ces 3 champs
```
`imdb_url` : construit directement depuis le `imdb_id` deja disponible
(pas besoin de TMDB) : `f"https://www.imdb.com/title/{imdb_id}/"` si
`imdb_id` est present.

## C. Extraction MediaInfo par piste + drapeaux

**`nfogen/extract.py`** — `extract_video_metadata()` gagne deux cles,
en plus des existantes (`audio_languages`/`subtitle_languages` restent,
utilisees ailleurs — cross-checks, name_proposal) :

```python
"audio_tracks": [
    {"language": "fre", "channels": "5.1", "codec": "AC-3",
     "bit_rate_kbps": 448, "sampling_khz": 48.0},
    ...
],
"subtitle_tracks": [
    {"language": "fre", "forced": True},
    {"language": "fre", "forced": False},
    ...
],
```
Sources MediaInfo par piste Audio : `.channel_s`, `.format`, `.bit_rate`
(÷1000), `.sampling_rate` (÷1000). Piste Text : `.language`, `.forced`
(`"Yes"`/`"No"`, absent → `False`). `extract_video_dir_metadata()`
propage ces cles sans changement de forme (deja le cas pour les cles
existantes).

**`nfogen/languages.py` (nouveau)** — mapping restreint mais couvrant les
langues courantes d'upload (francais/anglais/japonais/espagnol/allemand/
italien + `original`/`und` non mappes → pas de drapeau, langue affichee
telle quelle) :
```python
LANGUAGE_INFO: dict[str, tuple[str, str]] = {
    # code MediaInfo normalise -> (nom affiche FR, code drapeau ISO 3166-1)
    "fr": ("Français", "fr"), "fre": ("Français", "fr"), "fra": ("Français", "fr"),
    "en": ("Anglais", "gb"), "eng": ("Anglais", "gb"),
    "ja": ("Japonais", "jp"), "jpn": ("Japonais", "jp"),
    "es": ("Espagnol", "es"), "spa": ("Espagnol", "es"),
    "de": ("Allemand", "de"), "ger": ("Allemand", "de"), "deu": ("Allemand", "de"),
    "it": ("Italien", "it"), "ita": ("Italien", "it"),
}
def resolve_language(code: str) -> tuple[str, Optional[str]]:
    """Renvoie (nom affiche, code drapeau ou None si inconnu)."""
```
Utilise a la fois par `upload_prep.py` (pour construire les lignes du
tableau) et reutilisable plus tard par d'autres profils.

**Assemblage dans `upload_prep.py`** : transforme
`first_metadata["audio_tracks"]`/`["subtitle_tracks"]` en lignes pretes
pour le template (nom affiche + code drapeau deja resolus — le template
reste simple, sans logique de mapping dedans) :
```python
audio_rows = [
    {"flag": flagcdn_url(code) if code else None, "language": name,
     "channels": t["channels"], "codec": t["codec"],
     "bit_rate_kbps": t["bit_rate_kbps"], "sampling_khz": t["sampling_khz"]}
    for t in audio_tracks
    for name, code in [resolve_language(t["language"])]
]
```
`flagcdn_url(code)` : `f"https://flagcdn.com/20x15/{code}.png"` (meme
service et taille que l'exemple C411, domaine public deja utilise par
des trackers reels).

## D. Bannieres + refonte du template

**Generation (one-shot, hors runtime nfogen)** : nouveau script
`scripts/generate_upload_banners.py`, dependance dev-only `Pillow`
(ajoutee a `[project.optional-dependencies].dev` dans `pyproject.toml`,
jamais requise pour faire tourner nfogen normalement). Genere 4 PNG,
memes couleurs que l'appli (fond `#141d19`, texte/icone `#6bc9b3`),
credit `nfogen.nfo` integre en petit dans le coin, commites dans
`assets/banners/` :
- `informations.png`
- `synopsis.png`
- `details-techniques.png`
- `telechargement.png`

Servis via `https://raw.githubusercontent.com/ICCUser/nfogen/main/assets/banners/<nom>.png`
— URLs codees en constantes dans `upload_prep.py` (pas de config
utilisateur, ce sont des assets nfogen, pas des reglages).

**`upload_description.j2` refondu** — structure finale :

```jinja2
[center][size=150]{{ title }}[/size][/center]

{% if poster_url %}[center][img]{{ poster_url }}[/img][/center]

{% endif %}[img]{{ banner_informations }}[/img]
{% if genres %}[b]Genres :[/b] {{ genres|join(", ") }}
{% endif %}{% if country %}[b]Pays :[/b] {{ country }}
{% endif %}{% if release_date %}[b]Date de sortie :[/b] {{ release_date }}
{% endif %}{% if runtime_display %}[b]Durée :[/b] {{ runtime_display }}
{% endif %}{% if certification %}[b]Classification :[/b] {{ certification }}
{% endif %}{% if distributor %}[b]Studio/Chaîne :[/b] {{ distributor }}
{% endif %}{% if creators %}[b]Créateur(s) :[/b] {{ creators|join(", ") }}
{% endif %}{% if directors %}[b]Réalisateur(s) :[/b] {{ directors|join(", ") }}
{% endif %}{% if tmdb_rating %}[b]Note TMDB :[/b] {{ tmdb_rating }}/10
{% endif %}{% if imdb_url %}[b]IMDB :[/b] [url={{ imdb_url }}]Fiche{% endif %}
{% if cast %}[b]Acteurs :[/b] {{ cast|join(", ") }}
{% endif %}
[img]{{ banner_synopsis }}[/img]
{% if overview %}{{ overview }}{% else %}(synopsis non disponible){% endif %}

[img]{{ banner_details_techniques }}[/img]
[list]
[*]Vidéo : {{ video_codec }} {{ resolution }}p ({{ source }})
{% if video_bit_rate_kbps %}[*]Débit vidéo : {{ video_bit_rate_kbps }} kb/s
{% endif %}[/list]
{% if audio_rows %}[table][tr][th]#[/th][th]Langue[/th][th]Canaux[/th][th]Codec[/th][th]Débit[/th][th]Sample Rate[/th][/tr]
{% for a in audio_rows %}[tr][td]{{ loop.index }}[/td][td]{% if a.flag %}[img={{ flag_size }}]{{ a.flag }}[/img] {% endif %}{{ a.language }}[/td][td]{{ a.channels }}[/td][td]{{ a.codec }}[/td][td]{{ a.bit_rate_kbps }} kb/s[/td][td]{{ a.sampling_khz }} kHz[/td][/tr]
{% endfor %}[/table]
{% endif %}{% if subtitle_rows %}[table][tr][th]#[/th][th]Langue[/th][th]Type[/th][/tr]
{% for s in subtitle_rows %}[tr][td]{{ loop.index }}[/td][td]{% if s.flag %}[img={{ flag_size }}]{{ s.flag }}[/img] {% endif %}{{ s.language }}[/td][td]{{ "FORCÉ" if s.forced else "COMPLET" }}[/td][/tr]
{% endfor %}[/table]
{% endif %}
[img]{{ banner_telechargement }}[/img]
[b]Release :[/b] {{ release_name }}
{% if team %}[b]Team :[/b] {{ team }}
{% endif %}[b]Nombre de fichier(s) :[/b] {{ file_count }}
[b]Taille totale :[/b] {{ total_size_bytes|human_bin }}

[i]Généré par nfogen.nfo[/i]
```

Toutes les nouvelles lignes restent conditionnelles — un champ manquant
disparait, exactement comme le reste du template.

## Gestion d'erreur — recapitulatif

| Panne | Comportement |
|---|---|
| Cle TMDB non configuree | Aucun appel TMDB ; pays/createurs/note absents (silencieux, decision utilisateur) |
| Appel TMDB echoue (reseau/401/timeout) | `TMDBError` attrapee dans `send_to_tracker`, memes champs absents, reste de la description generee normalement |
| MediaInfo sans piste audio/sous-titre | `audio_rows`/`subtitle_rows` vides → tableau BBCode omis entierement |
| Langue MediaInfo non reconnue par `languages.py` | Nom affiche = code brut, pas de drapeau (`flag: None`) |
| Bannieres GitHub inaccessibles (rate-limit brut improbable, mais possible) | Hors controle de nfogen — meme risque deja accepte pour `poster_url` (TMDB) existant |

## Tests

- `tests/test_tmdb_client.py` (nouveau) : parsing film/serie, gestion
  d'erreur HTTP/JSON, `vote_average` nul traite comme absent.
- `tests/test_extract.py` : etendu pour `audio_tracks`/`subtitle_tracks`
  par piste (fixtures MediaInfo existantes, verifier les nouvelles cles).
- `tests/test_upload_prep.py` : etendu — TMDB appele seulement si cle
  configuree ET `tmdb_id` present ; `TMDBError` n'interrompt jamais
  `send_to_tracker` ; `audio_rows`/`subtitle_rows` correctement construits
  a partir de `extract_video_metadata`.
- `tests/test_upload_description.py` : etendu — rendu des bannieres,
  tableaux BBCode, nouveaux champs conditionnels (present/absent).
- `tests/test_gapscan_config_store.py` : `tmdb_api_key` write/lecture/
  variable d'environnement.
- `tests/test_api.py` : `GapscanConfig.tmdb_configured`.
- `frontend/src/pages/SettingsPage.test.tsx` (nouveau) : panneau config
  globale migre + champ TMDB, sauvegarde, deploi automatique.
- `frontend/src/pages/LibraryPage.test.tsx` : retrait des tests du
  panneau global (deplaces dans `SettingsPage.test.tsx`), le panneau
  "Configuration du profil" reste inchange.

## Hors perimetre (explicitement)

- Refonte du systeme de droits/comptes (deja differee par l'utilisateur).
- Support d'un tracker autre que C411 pour ce template (reste
  `profiles/c411/templates/`).
- Generation dynamique des bannieres a la demande (assets statiques
  uniquement).
- Toute ecriture vers TMDB (lecture seule).
- Renommage du repo GitHub (`nfogen.nfo`) — evoque en passant par
  l'utilisateur, casserait les URLs `raw.githubusercontent.com` de ce
  design ; a traiter separement si souhaite un jour.
