"""Moteur de regles declaratif, generique pour tout profil.

Un profil decrit ses exigences de nommage par categorie dans un fichier JSON
(voir profiles/c411/rules.json pour un exemple complet), interprete ici sans
aucune connaissance d'un tracker en particulier.

Schema attendu pour une categorie :
{
  "requires_field": "release_name",
  "doc": "description humaine de la convention",
  "example": "exemple conforme",
  "forbid_spaces": true,
  "forbid_non_ascii": true,
  "tokens": [
    {
      "name": "video_codec_team",
      "pattern": "\\.(?P<video_codec>x264|x265)-[A-Za-z0-9-]+$",
      "level": "required",
      "group": "identifier",
      "error": "message si absent et 'required'",
      "warning": "message si absent et 'recommended'"
    }
  ],
  "require_one_of_groups": {"identifier": "message si aucun token du groupe ne matche"},
  "filename_template": "{release_name}.nfo",
  "cross_checks": [
    {
      "capture": "resolution",
      "metadata_field": "video_height",
      "comparator": "int_equals",
      "message": "... ({capture}) ... ({actual}) ..."
    }
  ],
  "track_language_checks": [
    {
      "metadata_field": "audio_languages",
      "label": "Piste audio",
      "hint_capture": "language",
      "warn_if_empty": "message si la liste de pistes est vide"
    }
  ]
}
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
import re2

# Les patterns admin (tokens[].pattern) sont executes via RE2 (temps lineaire
# garanti, pas de backtracking exponentiel) plutot que `re` : protection ReDoS
# a la fois a la validation et a chaque generation. Contrepartie : RE2
# n'accepte ni lookaround ni back-reference.
_RE2_OPTIONS = re2.Options()
_RE2_OPTIONS.log_errors = False  # evite le bruit stderr d'abseil sur un motif invalide


@lru_cache(maxsize=256)
def _compile_admin_pattern(pattern: str):
    return re2.compile(pattern, options=_RE2_OPTIONS)


def validate_regex_patterns(document: dict[str, Any]) -> None:
    """Verifie que tous les `tokens[].pattern` d'un rules.json compilent sous RE2."""
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
                    "RE2 n'accepte ni lookaround ((?=...), (?<=...), (?!...)) ni back-reference (\\1)."
                ) from exc


def _search(pattern: str, value: str):
    return _compile_admin_pattern(pattern).search(value)


def _tokens(schema: dict[str, Any]) -> list[dict[str, Any]]:
    return schema.get("tokens", [])


def required_value(data: dict[str, Any], schema: dict[str, Any]) -> Any:
    field = schema.get("requires_field")
    value = data.get(field) if field else None
    if not value:
        doc = schema.get("doc", "")
        example = schema.get("example", "")
        suffix = f" ({doc}, ex: {example})." if doc else "."
        raise ValueError(f"Champ obligatoire manquant : '{field}'{suffix}")
    return value


def errors(value: str, schema: dict[str, Any]) -> list[str]:
    """Verifications bloquantes : separateur/accents, tokens 'required', groupes."""
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
    """Tokens 'recommended' absents."""
    found: list[str] = []
    for token in _tokens(schema):
        if token.get("level") != "recommended":
            continue
        if not _search(token["pattern"], value):
            found.append(token.get("warning", f"motif recommande absent : {token['name']}"))
    return found


def validate_and_get(data: dict[str, Any], schema: dict[str, Any]) -> str:
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
    """Valeurs des groupes nommes `(?P<...>)` trouves dans les tokens."""
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
        return True


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
    """Compare les valeurs declarees (release_name) aux metadonnees reelles du fichier."""
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
    """Avertit pour chaque piste sans langue declaree dans les metadonnees."""
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
    """Valide un rules.json (schema formel, puis securite des motifs regex)."""
    try:
        jsonschema.validate(document, _schema())
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "racine"
        raise ValueError(f"rules.json invalide a '{location}' : {exc.message}") from exc
    validate_regex_patterns(document)
