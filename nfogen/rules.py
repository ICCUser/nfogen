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
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema


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
        match = re.search(token["pattern"], value)
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
        if not re.search(token["pattern"], value):
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
        match = re.search(token["pattern"], value)
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
    """Valide un `rules.json` complet (toutes categories) contre le schema
    formel (`rules.schema.json`). Leve une `ValueError` documentee si non
    conforme ; ne renvoie rien sinon.

    Utilise a l'enregistrement de tout profil declaratif (`declarative_profile.
    register_declarative_profile`, y compris pour C411 lui-meme) ainsi qu'a
    l'ecriture/import d'un profil utilisateur (`profile_store`), pour detecter
    une erreur d'edition avant qu'elle n'atteigne le moteur de regles."""
    try:
        jsonschema.validate(document, _schema())
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "racine"
        raise ValueError(f"rules.json invalide a '{location}' : {exc.message}") from exc