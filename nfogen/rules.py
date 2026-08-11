"""Moteur de regles declaratif, generique pour tout profil.

Un profil decrit ses exigences de nommage par categorie dans un fichier JSON
(voir profiles/c411/rules.json pour un exemple complet), interprete ici sans
aucune connaissance d'un tracker en particulier. Ajouter ou modifier une
regle pour un profil existant = editer ce JSON ; ce module et le coeur
(engine.py/registry.py) ne doivent jamais changer pour ca.

Schema attendu pour une categorie :
{
  "requires_field": "release_name",        # champ obligatoire dans ctx.data
  "doc": "description humaine de la convention",
  "example": "exemple conforme",
  "forbid_spaces": true,
  "forbid_non_ascii": true,
  "tokens": [
    {
      "name": "video_codec_team",
      "pattern": "\\.(?P<video_codec>x264|x265)-[A-Za-z0-9-]+$",
      "level": "required",                 # ou "recommended" (defaut)
      "group": "identifier",               # optionnel, pour require_one_of_groups
      "error": "message si absent et 'required'",
      "warning": "message si absent et 'recommended'"
    }
  ],
  "require_one_of_groups": {"identifier": "message si aucun token du groupe ne matche"},
  "filename_template": "{release_name}.nfo",
  "cross_checks": [
    {
      "capture": "resolution",             # nom du groupe nomme capture par un token
      "metadata_field": "video_height",    # cle dans les metadonnees extraites du fichier
      "comparator": "int_equals",          # ou "codec_alias" (+ "aliases": {...})
      "message": "... ({capture}) ... ({actual}) ..."
    }
  ],
  "track_language_checks": [
    {
      "metadata_field": "audio_languages", # liste de langues par piste (ou None)
      "label": "Piste audio",
      "hint_capture": "language",          # optionnel : suggestion tiree d'un token capture
      "warn_if_empty": "message si la liste de pistes est vide"
    }
  ]
}

Les "comparateurs" (`_COMPARATORS`) sont le seul code reellement specifique a
un type de verification ; ils restent volontairement en tres petit nombre et
generiques (pas de notion de tracker). Tout le reste (quels champs comparer,
avec quel message) est de la donnee.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
import re2

# --------------------------------------------------------------------------- #
# Moteur de correspondance pour les patterns ADMIN (tokens[].pattern d'un
# rules.json) : RE2 (paquet `google-re2`), jamais le `re` de la bibliotheque
# standard.
# --------------------------------------------------------------------------- #
# `re` (moteur a backtracking) peut exploser en temps EXPONENTIEL sur certains
# motifs pathologiques (ReDoS, ex. `(a+)+$`) des qu'on lui donne une entree
# "presque" conforme -- un seul `re.search()` de ce type bloquerait le
# processus uvicorn (mono-process) pendant des secondes/minutes, pour
# n'importe quel motif de ce type, meme un motif qui semblait sain lors d'un
# test superficiel sur quelques exemples.
#
# RE2 n'a pas ce probleme PAR CONSTRUCTION : c'est un moteur a automate fini
# (pas de backtracking), qui garantit un temps lineaire en la taille de
# l'entree, quel que soit le motif -- verifie empiriquement en audit :
# `(a+)+$` s'execute en quelques microsecondes sous RE2 contre un blocage
# total sous `re`. Consequence directe : il n'y a plus besoin de DETECTER un
# motif dangereux a l'ecriture (approche heuristique par chronometrage,
# dependante de la vitesse de la machine et d'une entree de sonde choisie a
# l'avance, donc potentiellement contournable par un motif qui explose
# seulement sur une AUTRE forme d'entree) -- on rend l'explosion tout
# simplement IMPOSSIBLE en executant CHAQUE motif admin via RE2, aussi bien a
# la validation d'un profil qu'a chaque generation.
#
# Prix a payer, accepte en connaissance de cause : RE2 ne supporte ni les
# lookaround (`(?=...)`, `(?<=...)`, `(?!...)`) ni les references arrieres
# (`\1`) -- des constructions qui permettent JUSTEMENT le backtracking
# exponentiel, donc precisement ce qu'on veut exclure des motifs admin. Un
# motif qui en a besoin est rejete a la validation, avec un message explicite
# (jamais une erreur silencieuse). Verifie : les 6 patterns du profil C411
# fourni (`nfogen/profiles/c411/rules.json`) n'en utilisent aucun et
# compilent tels quels sous RE2, sans aucune reecriture.
_RE2_OPTIONS = re2.Options()
_RE2_OPTIONS.log_errors = False
# Sans ceci, la bibliotheque C++ sous-jacente (abseil) ecrit EN PLUS un
# message brut directement sur stderr a chaque motif rejete -- y compris pour
# une simple faute de frappe d'un admin en train d'iterer sur son profil. On
# garde le controle exclusif de la restitution de l'erreur : `re2.error` est
# deja capturee et traduite en `ValueError` explicite par `validate_regex_
# patterns` ci-dessous.


@lru_cache(maxsize=256)
def _compile_admin_pattern(pattern: str):
    """Compile un pattern admin sous RE2 (jamais `re`), avec cache : un
    profil declare peu de tokens (quelques dizaines au plus), un `rules.json`
    change rarement, donc le cache reste petit et stable pour la duree de vie
    du processus. Leve `re2.error` si le motif est syntaxiquement invalide OU
    utilise une construction non supportee par RE2 (lookaround, back-
    reference) -- les DEUX cas sont voulus ici, RE2 n'accepte tout simplement
    pas les constructions qui permettraient un backtracking exponentiel."""
    return re2.compile(pattern, options=_RE2_OPTIONS)


def validate_regex_patterns(document: dict[str, Any]) -> None:
    """Verifie que TOUS les motifs `pattern` declares dans un `rules.json`
    (champ `tokens[].pattern` de chaque categorie) compilent sous RE2. Leve
    une `ValueError` documentee (categorie + nom du token fautif) si l'un
    d'eux est invalide ou utilise une construction non supportee (lookaround,
    back-reference).

    Appelee automatiquement par `validate_rules_document` ci-dessous : il n'y
    a donc qu'UN SEUL point d'entree a couvrir pour qu'un `rules.json` -- livre
    avec le paquet, ecrit/importe via l'API (`profile_store.write_profile`),
    ou depose directement dans `NFOGEN_PROFILES_DIR` -- passe par cette
    verification, quel que soit le chemin d'appel. Reste exportee separement
    (plutot que privee) pour rester testable independamment de la validation
    de schema."""
    for category, schema in document.items():
        if not isinstance(schema, dict):
            continue
        for token in schema.get("tokens", []):
            pattern = token.get("pattern")
            if not isinstance(pattern, str):
                continue
            try:
                _compile_admin_pattern(pattern)
            except re2.error as exc:
                raise ValueError(
                    f"Regex invalide ou non supportee dans "
                    f"'{category}.tokens[{token.get('name', '?')}].pattern' ({pattern!r}) : {exc}. "
                    "Les motifs admin sont executes via RE2 (temps lineaire garanti, "
                    "protection ReDoS) : ni lookaround ((?=...), (?<=...), (?!...)) ni "
                    "back-reference (\\1) ne sont supportes, ce sont justement les "
                    "constructions qui permettraient un temps d'execution exponentiel."
                ) from exc


def _search(pattern: str, value: str):
    """Point d'entree UNIQUE pour faire correspondre un pattern admin a une
    valeur : toujours via RE2 (`_compile_admin_pattern`), jamais `re.search`
    directement, pour que la garantie de temps lineaire s'applique a chaque
    generation, pas seulement a la validation d'un profil."""
    return _compile_admin_pattern(pattern).search(value)


def _tokens(schema: dict[str, Any]) -> list[dict[str, Any]]:
    return schema.get("tokens", [])


def required_value(data: dict[str, Any], schema: dict[str, Any]) -> Any:
    """Renvoie la valeur du champ declare par `requires_field`, ou leve une
    ValueError documentee (doc/example du schema) si absent."""
    field = schema.get("requires_field")
    value = data.get(field) if field else None
    if not value:
        doc = schema.get("doc", "")
        example = schema.get("example", "")
        suffix = f" ({doc}, ex: {example})." if doc else "."
        raise ValueError(f"Champ obligatoire manquant : '{field}'{suffix}")
    return value


def errors(value: str, schema: dict[str, Any]) -> list[str]:
    """Verifications bloquantes : separateur/accents + tokens 'required' +
    au moins un token present par groupe declare dans require_one_of_groups."""
    found: list[str] = []
    if schema.get("forbid_spaces") and " " in value:
        found.append("contient un espace (seul le point separe les mots)")
    if schema.get("forbid_non_ascii") and not value.isascii():
        found.append("contient un accent ou un caractere non standard")

    matched_groups: set[str] = set()
    for token in _tokens(schema):
        match = _search(token["pattern"], value)
        if match:
            if "group" in token:
                matched_groups.add(token["group"])
            continue
        if token.get("level") == "required":
            found.append(token.get("error", f"motif obligatoire absent : {token['name']}"))

    for group, message in schema.get("require_one_of_groups", {}).items():
        if group not in matched_groups:
            found.append(message)

    return found


def warnings(value: str, schema: dict[str, Any]) -> list[str]:
    """Verifications informatives : tokens explicitement 'recommended'
    absents. Un token sans 'level' (ex. membre d'un groupe alternatif) n'est
    verifie qu'au niveau du groupe (`require_one_of_groups`), jamais ici."""
    found: list[str] = []
    for token in _tokens(schema):
        if token.get("level") != "recommended":
            continue
        if not _search(token["pattern"], value):
            found.append(token.get("warning", f"motif recommande absent : {token['name']}"))
    return found


def validate_and_get(data: dict[str, Any], schema: dict[str, Any]) -> str:
    """Recupere puis valide le champ obligatoire du schema ; leve une
    ValueError documentee si absent ou non conforme, renvoie sa valeur sinon.
    """
    value = required_value(data, schema)
    found = errors(value, schema)
    if found:
        doc = schema.get("doc", "")
        example = schema.get("example", "")
        suffix = f" ({doc}, ex: {example})." if doc else "."
        field = schema.get("requires_field")
        raise ValueError(f"{field} '{value}' non conforme : {'; '.join(found)}.{suffix}")
    return value


def captures(value: str, schema: dict[str, Any]) -> dict[str, str]:
    """Valeurs des groupes nommes `(?P<...>)` trouves dans les tokens, ex.
    {'language': 'VFF', 'resolution': '1080', 'video_codec': 'x264'}."""
    out: dict[str, str] = {}
    for token in _tokens(schema):
        match = _search(token["pattern"], value)
        if match:
            out.update({k: v for k, v in match.groupdict().items() if v is not None})
    return out


def _comparator_int_equals(capture_val: str, actual_val: Any, _opts: dict[str, Any]) -> bool:
    try:
        return int(capture_val) == int(actual_val)
    except (TypeError, ValueError):
        return True  # rien de comparable, pas de fausse alerte


def _comparator_codec_alias(capture_val: str, actual_val: Any, opts: dict[str, Any]) -> bool:
    if not actual_val:
        return True
    aliases = opts.get("aliases", {}).get(capture_val.lower().replace(".", ""), [])
    actual = str(actual_val).lower()
    return any(alias in actual for alias in aliases) if aliases else True


_COMPARATORS = {
    "int_equals": _comparator_int_equals,
    "codec_alias": _comparator_codec_alias,
}


def cross_check_warnings(
    capture_values: dict[str, str], metadata: dict[str, Any], schema: dict[str, Any]
) -> list[str]:
    """Compare les valeurs declarees (captures du release_name) aux donnees
    reelles extraites du fichier (metadata), via un comparateur generique
    nomme. Silencieux si rien n'est comparable (capture ou champ absent)."""
    found: list[str] = []
    for check in schema.get("cross_checks", []):
        capture_val = capture_values.get(check["capture"])
        actual_val = metadata.get(check["metadata_field"])
        if capture_val is None or actual_val is None:
            continue
        comparator = _COMPARATORS.get(check["comparator"])
        if comparator is None or comparator(capture_val, actual_val, check):
            continue
        found.append(check["message"].format(capture=capture_val, actual=actual_val))
    return found


def track_language_warnings(
    metadata: dict[str, Any], schema: dict[str, Any], capture_values: dict[str, str]
) -> list[str]:
    """Avertit pour chaque piste (audio/sous-titres...) sans langue declaree
    dans les metadonnees, en suggerant la valeur capturee du release_name si
    declaree (`hint_capture`). On ne devine jamais : on rappelle seulement
    une information que l'appelant a deja fournie lui-meme."""
    found: list[str] = []
    for check in schema.get("track_language_checks", []):
        languages = metadata.get(check["metadata_field"]) or []
        if not languages:
            if check.get("warn_if_empty"):
                found.append(check["warn_if_empty"])
            continue
        hint = capture_values.get(check.get("hint_capture", ""))
        for i, lang in enumerate(languages, start=1):
            if lang:
                continue
            msg = (
                f"{check['label']} {i} : langue non declaree dans les metadonnees du "
                "fichier (MediaInfo ne pourra pas l'afficher)."
            )
            if hint:
                msg += (
                    f" Le release_name indique '{hint}' : verifiez que c'est bien la "
                    "langue de cette piste et completez le tag MediaInfo si besoin."
                )
            else:
                msg += " Aucune langue detectee non plus dans release_name ; completez manuellement."
            found.append(msg)
    return found


def render_filename(data: dict[str, Any], schema: dict[str, Any]) -> str:
    """Construit le nom de fichier impose par `filename_template` (ex.
    '{release_name}.nfo'.format(**data))."""
    template = schema.get("filename_template")
    if not template:
        raise ValueError("Aucun filename_template declare pour cette categorie.")
    try:
        return template.format(**data)
    except KeyError as exc:
        raise ValueError(f"Champ manquant pour construire le nom de fichier : {exc}") from exc


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    path = Path(__file__).parent / "rules.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validate_rules_document(document: dict[str, Any]) -> None:
    """Valide un `rules.json` complet (toutes categories) : conformite au
    schema formel (`rules.schema.json`), PUIS securite des motifs regex
    (`validate_regex_patterns`, protection ReDoS via RE2). Leve une
    `ValueError` documentee au premier probleme rencontre ; ne renvoie rien
    sinon.

    Point d'entree UNIQUE pour ces deux verifications : utilise a
    l'enregistrement de tout profil declaratif
    (`declarative_profile.register_declarative_profile`, y compris pour C411
    lui-meme) ainsi qu'a l'ecriture/import d'un profil utilisateur
    (`profile_store`) -- aucun de ces appelants n'a besoin d'appeler
    `validate_regex_patterns` separement, ce qui evite qu'un futur chemin
    d'enregistrement de profil (ex. une commande CLI de gestion de profils)
    oublie l'un des deux controles."""
    try:
        jsonschema.validate(document, _schema())
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "racine"
        raise ValueError(f"rules.json invalide a '{location}' : {exc.message}") from exc
    validate_regex_patterns(document)
