"""Interface en ligne de commande de nfogen.

Exemples :
    nfogen --list
    nfogen -i film.mkv                       # categorie auto-detectee
    nfogen -c video -i film.mkv -o film.nfo
    nfogen -c audio -i /dossier/album -o album.nfo
    nfogen -c game --data jeu.json -o jeu.nfo
    nfogen --propose-name -c video -i "Season 01"  # suggestion de release_name

Gestion de profils utilisateur (equivalent CLI des routes `/profiles/store*`
de l'API, cf. `nfogen/profile_store.py` -- necessite NFOGEN_PROFILES_DIR) :
    nfogen --profile-store-list
    nfogen --profile-store-show c411
    nfogen --profile-store-write mon_tracker --rules-file rules.json --templates-dir templates/
    nfogen --profile-store-delete mon_tracker
    nfogen --profile-store-export c411 -o c411.zip
    nfogen --profile-store-import mon_tracker --zip-file mon_tracker.zip
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import engine, profile_store


def _load_data(path: str | None) -> dict:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _video_entries_for_source(source: str, category: str | None) -> list[Path]:
    """Fichiers a considerer pour la proposition de nom (filtre les extensions video)."""
    path = Path(source)
    if not path.is_dir():
        return [path]
    entries = sorted(p for p in path.iterdir() if p.is_file())
    if category == "video":
        from . import extract

        entries = [p for p in entries if p.suffix.lower() in extract.VIDEO_EXTS]
    return entries


def _filenames_for_source(source: str, category: str | None) -> list[str]:
    """Noms de fichiers a transmettre a `engine.propose_release_name`."""
    return [p.name for p in _video_entries_for_source(source, category)]


def _title_hints_for_source(source: str, category: str | None) -> list[str | None] | None:
    """Tag `Title` du conteneur de chaque fichier video (best-effort, cf. `name_proposal`)."""
    if category != "video":
        return None
    from . import extract

    hints: list[str | None] = []
    for p in _video_entries_for_source(source, category):
        try:
            hints.append(extract.extract_video_metadata(p).get("general_title"))
        except Exception:
            hints.append(None)
    return hints


def _load_templates_dir(path: str | None) -> dict[str, str]:
    """Lit chaque `<categorie>.j2` d'un dossier de templates en `{categorie: contenu}`."""
    if not path:
        return {}
    templates_dir = Path(path)
    if not templates_dir.is_dir():
        raise ValueError(f"--templates-dir n'est pas un dossier existant : {path}")
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(templates_dir.glob("*.j2"))}


def _run_profile_store_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int | None:
    """Execute l'action `--profile-store-*` demandee. `None` si aucune n'a ete fournie."""
    try:
        if args.profile_store_list:
            for name in profile_store.list_profiles():
                print(name)
            return 0

        if args.profile_store_show:
            data = profile_store.read_profile(args.profile_store_show)
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return 0

        if args.profile_store_write:
            rules = _load_data(args.rules_file)
            templates = _load_templates_dir(args.templates_dir)
            profile_store.write_profile(args.profile_store_write, rules=rules, templates=templates)
            print(f"Profil ecrit : {args.profile_store_write}", file=sys.stderr)
            return 0

        if args.profile_store_delete:
            profile_store.delete_profile(args.profile_store_delete)
            print(f"Profil supprime : {args.profile_store_delete}", file=sys.stderr)
            return 0

        if args.profile_store_export:
            if not args.out:
                parser.error("--profile-store-export necessite -o/--out (chemin du .zip a ecrire)")
            content = profile_store.export_profile_zip(args.profile_store_export)
            Path(args.out).write_bytes(content)
            print(f"Profil exporte : {args.out}", file=sys.stderr)
            return 0

        if args.profile_store_import:
            if not args.zip_file:
                parser.error("--profile-store-import necessite --zip-file")
            content = Path(args.zip_file).read_bytes()
            profile_store.import_profile_zip(args.profile_store_import, content)
            print(f"Profil importe : {args.profile_store_import}", file=sys.stderr)
            return 0
    except Exception as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1

    return None


def _resolve_output_path(out_arg: str | None, canonical_name: str | None) -> str | None:
    """Chemin de sortie final, en respectant le nom impose par le profil s'il y en a un."""
    if out_arg is None:
        return None
    if canonical_name is None:
        return out_arg
    out_path = Path(out_arg)
    if out_path.is_dir():
        return str(out_path / canonical_name)
    if out_path.name != canonical_name:
        raise ValueError(
            f"Nom de fichier '{out_path.name}' non conforme au profil : "
            f"attendu '{canonical_name}'. Utilisez -o '{canonical_name}' ou "
            "-o pointant vers un dossier pour laisser nfogen choisir le nom."
        )
    return out_arg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nfogen", description="Generateur de fichiers NFO base sur des profils."
    )
    parser.add_argument("-p", "--profile", default="c411", help="Profil (defaut: c411)")
    parser.add_argument("-c", "--category", help="Categorie (auto si omis)")
    parser.add_argument("-i", "--in", dest="source", help="Fichier ou dossier source")
    parser.add_argument(
        "-o", "--out",
        help="Fichier ou dossier .nfo de sortie (sinon: stdout). Si le profil "
        "impose un nom de fichier, donner un dossier laisse nfogen le choisir ; "
        "donner un nom precis doit alors correspondre exactement.",
    )
    parser.add_argument("--data", help="Fichier JSON de metadonnees complementaires")
    parser.add_argument("--full", action="store_true", help="Video: sortie MediaInfo complete")
    parser.add_argument("--list", action="store_true", help="Lister profils/categories")
    parser.add_argument(
        "--propose-name",
        action="store_true",
        help="Proposer un release_name a partir des noms de fichiers de --in (sans generer le NFO)",
    )
    store_group = parser.add_argument_group(
        "Gestion de profils utilisateur",
        "Equivalent CLI des routes /profiles/store* de l'API (necessite NFOGEN_PROFILES_DIR).",
    )
    store_group.add_argument(
        "--profile-store-list", action="store_true", help="Lister les profils utilisateur"
    )
    store_group.add_argument(
        "--profile-store-show", metavar="NOM", help="Afficher regles + templates d'un profil (JSON)"
    )
    store_group.add_argument(
        "--profile-store-write", metavar="NOM", help="Creer/remplacer un profil utilisateur"
    )
    store_group.add_argument(
        "--rules-file", help="Fichier rules.json (avec --profile-store-write ; defaut : aucune regle)"
    )
    store_group.add_argument(
        "--templates-dir", help="Dossier de templates *.j2 (avec --profile-store-write)"
    )
    store_group.add_argument("--profile-store-delete", metavar="NOM", help="Supprimer un profil utilisateur")
    store_group.add_argument(
        "--profile-store-export", metavar="NOM", help="Exporter un profil en .zip (avec -o)"
    )
    store_group.add_argument(
        "--profile-store-import", metavar="NOM", help="Creer/remplacer un profil depuis un .zip"
    )
    store_group.add_argument("--zip-file", help="Fichier .zip source (avec --profile-store-import)")
    args = parser.parse_args(argv)

    store_exit_code = _run_profile_store_command(args, parser)
    if store_exit_code is not None:
        return store_exit_code

    if args.list:
        for prof, cats in engine.list_available().items():
            print(f"{prof}: {', '.join(cats)}")
        return 0

    if args.propose_name:
        if not args.source:
            parser.error("--propose-name necessite --in")
        category = args.category or "video"
        try:
            proposal = engine.propose_release_name(
                category=category,
                profile=args.profile,
                filenames=_filenames_for_source(args.source, category),
                title_hints=_title_hints_for_source(args.source, category),
            )
        except Exception as exc:
            print(f"Erreur : {exc}", file=sys.stderr)
            return 1
        for w in proposal.warnings:
            print(f"Avertissement : {w}", file=sys.stderr)
        if proposal.name is None:
            return 1
        print(proposal.name)
        return 0

    if not args.source and not args.data:
        parser.error("fournir --in (source) et/ou --data (metadonnees)")

    warnings: list[str] = []
    filename: list[str] = []
    try:
        nfo = engine.generate(
            category=args.category,
            profile=args.profile,
            source=args.source,
            data=_load_data(args.data),
            options={"full": args.full},
            warnings=warnings,
            filename=filename,
        )
        out_path = _resolve_output_path(args.out, filename[0] if filename else None)
    except Exception as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1

    for w in warnings:
        print(f"Avertissement : {w}", file=sys.stderr)

    if out_path:
        Path(out_path).write_text(nfo, encoding="utf-8")
        print(f"NFO ecrit : {out_path}", file=sys.stderr)
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(nfo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
