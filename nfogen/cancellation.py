"""Signal d'annulation partage entre les operations longues declenchees en
tache de fond (copie de fichier, hachage de torrent -- voir AUTOMATION.md,
sous-projet 4c). Module minuscule et neutre : file_staging.py et
torrent_builder.py n'ont aucune autre relation d'import entre eux, pas de
raison que l'un depende de l'autre pour cette seule exception.
"""
from __future__ import annotations


class OperationCancelled(RuntimeError):
    """Une operation (copie, hachage de torrent...) a ete interrompue via
    un threading.Event fourni par l'appelant (voir commit_job_runner.py)."""
