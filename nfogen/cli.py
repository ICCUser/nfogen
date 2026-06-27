"""Interface en ligne de commande de nfogen.

Exemples :
    nfogen --list
    nfogen -i film.mkv                       # categorie auto-detectee
    nfogen -c video -i film.mkv -o film.nfo
    nfogen -c audio -i /dossier/album -o album.nfo
    nfogen -c game --data jeu.json -o jeu.nfo
    nfogen --propose-name -c video -i "Season 01"  # suggestion de release_name
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import engine


def _load_data(path: str | None) -> dict:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _video_entries_for_source(source: str, category: str | None) -> list[Path]:
    """Fichiers a considerer pour la proposition de nom (noms ET, pour la
    video, tags `Title` embarques). Pour un dossier video, ne retient que les
    extensions video connues (cf. `extract.VIDEO_EXTS`) : un .srt/.nfo egare
    ne doit pas fausser la detection de saison/equipe."""
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
    """Tag `Title` du conteneur (piste General) de chaque fichier, dans le
    meme ordre que `_filenames_for_source`, pour affiner la proposition (cf.
    `nfogen.name_proposal`). Contrairement aux noms de fichiers, ceci lit
    l'entete du fichier (rapide, MediaInfo ne lit pas le flux video) -- mais
    seulement pour la categorie video, et de maniere best-effort (un fichier
    illisible donne simplement None pour cette entree, pas d'erreur)."""
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


def _resolve_output_path(out_arg: str | None, canonical_name: str | None) -> str | None:
    """Determine le chemin de sortie final, en respectant la regle de nommage
    du profil/categorie quand elle existe (`canonical_name`, ou None si le
    profil n'en impose pas).

    - Pas de -o : renvoie None (sortie stdout, le nom de fichier ne s'applique
      pas puisque rien n'est ecrit sur disque).
    - Pas de regle de nommage pour ce profil/categorie : -o est utilise tel
      quel (comportement historique, aucune contrainte).
    - -o pointe vers un dossier existant : on y ecrit sous le nom impose.
    - -o pointe vers un nom de fichier precis : il doit correspondre exactement
      au nom impose, sinon on refuse (le nom du NFO doit respecter le profil).
    """
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
    args = parser.parse_args(argv)

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
    except Exception as exc:  # message clair en CLI
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
