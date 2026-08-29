"""Client pour l'API Torznab de C411 (lecture seule, scope "Torznab/RSS").

Verifie en direct le 2026-08-25 contre `https://c411.org/api` : Torznab
standard (le protocole que parlent deja Prowlarr/Sonarr/Radarr/Jackett),
pas d'API maison. Voir `GAPSCAN.md` pour le detail des endpoints/attributs
observes (`downloadvolumefactor`/`uploadvolumefactor` pour les badges
FL/50%/2x, `imdbid`/`tmdbid` pas systematiquement presents).

Ce client ne telecharge, n'heberge et ne distribue aucun contenu : il ne
fait que lister des metadonnees de releases deja presentes sur le tracker,
pour comparaison avec la bibliotheque locale (voir `gapscan.py`).
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .quality import ReleaseQuality, parse_release_name

_TORZNAB_NS = "http://torznab.com/schemas/2015/feed"


class TorznabError(RuntimeError):
    """Erreur reseau ou reponse inattendue de l'API C411."""


@dataclass
class TorznabRelease:
    """Une release telle que listee par l'API Torznab de C411."""

    title: str
    guid: str
    link: str
    size: Optional[int] = None
    seeders: Optional[int] = None
    peers: Optional[int] = None
    grabs: Optional[int] = None
    category: Optional[str] = None
    infohash: Optional[str] = None
    imdb_id: Optional[str] = None
    tmdb_id: Optional[str] = None
    download_volume_factor: float = 1.0
    upload_volume_factor: float = 1.0
    pub_date: Optional[str] = None
    quality: ReleaseQuality = field(init=False)

    def __post_init__(self) -> None:
        self.quality = parse_release_name(self.title)

    @property
    def is_freeleech(self) -> bool:
        return self.download_volume_factor == 0

    @property
    def is_half_leech(self) -> bool:
        return self.download_volume_factor == 0.5

    @property
    def is_double_upload(self) -> bool:
        return self.upload_volume_factor == 2


def _attr(item: ET.Element, name: str) -> Optional[str]:
    el = item.find(f"{{{_TORZNAB_NS}}}attr[@name='{name}']")
    return el.get("value") if el is not None else None


def _attr_int(item: ET.Element, name: str) -> Optional[int]:
    value = _attr(item, name)
    return int(value) if value is not None else None


def _attr_float(item: ET.Element, name: str, default: float) -> float:
    value = _attr(item, name)
    return float(value) if value is not None else default


def _parse_item(item: ET.Element) -> TorznabRelease:
    return TorznabRelease(
        title=(item.findtext("title") or "").strip(),
        guid=(item.findtext("guid") or "").strip(),
        link=(item.findtext("link") or "").strip(),
        size=_attr_int(item, "size"),
        seeders=_attr_int(item, "seeders"),
        peers=_attr_int(item, "peers"),
        grabs=_attr_int(item, "grabs"),
        category=_attr(item, "category"),
        infohash=_attr(item, "infohash"),
        imdb_id=_attr(item, "imdbid"),
        tmdb_id=_attr(item, "tmdbid"),
        download_volume_factor=_attr_float(item, "downloadvolumefactor", 1.0),
        upload_volume_factor=_attr_float(item, "uploadvolumefactor", 1.0),
        pub_date=item.findtext("pubDate"),
    )


def parse_torznab_response(xml_text: str) -> list[TorznabRelease]:
    """Parse une reponse Torznab RSS/XML en liste de `TorznabRelease`.

    Fonction pure (pas de reseau) : testable directement sur des fixtures
    figees, cf. `tests/test_c411_client.py`.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise TorznabError(f"Reponse C411 illisible (XML invalide) : {exc}") from exc
    return [_parse_item(item) for item in root.iter("item")]


class TorznabClient:
    """Client HTTP pour l'API Torznab de C411 (recherche uniquement)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://c411.org/api",
        http_client: Optional[httpx.Client] = None,
        timeout: float = 20.0,
        min_interval_seconds: float = 0.0,
    ) -> None:
        """`min_interval_seconds` : pause minimale entre deux requetes
        (defaut 0 = desactive) -- un scan GapScan complet peut interroger
        des centaines de titres, cf. GAPSCAN.md section "Execution". Les
        limites exactes de l'API C411 n'etant pas documentees publiquement,
        `gapscan_runner.py` passe une valeur par defaut prudente plutot que
        de ne pas limiter du tout."""
        if not api_key:
            raise TorznabError("Cle API C411 manquante.")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None
        self._min_interval = min_interval_seconds
        self._last_request_at: Optional[float] = None
        # Surchargeables dans les tests (evite un vrai time.sleep).
        self._sleep = time.sleep
        self._time = time.monotonic

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        now = self._time()
        if self._last_request_at is not None:
            remaining = self._min_interval - (now - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = now

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TorznabClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    _DEFAULT_RETRY_AFTER_SECONDS = 5.0

    def _parse_retry_after(self, response: httpx.Response) -> float:
        raw = response.headers.get("retry-after")
        if raw is not None:
            try:
                return float(raw)
            except ValueError:
                pass  # ex. une date HTTP plutot qu'un nombre de secondes -- non geree, repli prudent
        return self._DEFAULT_RETRY_AFTER_SECONDS

    def _search(self, params: dict[str, str]) -> list[TorznabRelease]:
        # Incident reel (2026-08-25) : un intervalle trop agressif entre
        # requetes a declenche un 429. Un seul reessai apres Retry-After
        # (ou une valeur prudente par defaut) plutot que d'abandonner ce
        # titre immediatement -- gapscan.py continue de toute facon le
        # scan sur les titres suivants si ce reessai echoue aussi.
        for attempt in range(2):
            self._throttle()
            query = {k: v for k, v in params.items() if v is not None}
            query["apikey"] = self._api_key
            try:
                response = self._client.get(self._base_url, params=query)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt == 0:
                    self._sleep(self._parse_retry_after(exc.response))
                    continue
                raise TorznabError(
                    f"Appel a l'API C411 echoue ({params.get('t')}) : {self._redact(exc)}"
                ) from exc
            except httpx.HTTPError as exc:
                raise TorznabError(
                    f"Appel a l'API C411 echoue ({params.get('t')}) : {self._redact(exc)}"
                ) from exc
            return parse_torznab_response(response.text)
        raise AssertionError("unreachable")  # la boucle retourne ou leve dans tous les cas

    def _redact(self, exc: Exception) -> str:
        # httpx inclut l'URL complete (donc ?apikey=...) dans le message de
        # certaines erreurs (HTTPStatusError.__str__ notamment) -- sans
        # cette redaction, la cle finit affichee en clair cote utilisateur
        # (GET /gapscan/status) a chaque erreur reseau (incident reel,
        # 2026-08-25).
        return str(exc).replace(self._api_key, "<cle redigee>")

    def search_movie(
        self,
        query: Optional[str] = None,
        imdb_id: Optional[str] = None,
        tmdb_id: Optional[str] = None,
    ) -> list[TorznabRelease]:
        """`t=movie` : recherche par titre libre et/ou identifiant externe."""
        return self._search({"t": "movie", "q": query, "imdbid": imdb_id, "tmdbid": tmdb_id})

    def search_tv(
        self,
        query: Optional[str] = None,
        imdb_id: Optional[str] = None,
        tmdb_id: Optional[str] = None,
        season: Optional[int] = None,
        ep: Optional[int] = None,
    ) -> list[TorznabRelease]:
        """`t=tvsearch` : recherche par titre/identifiant externe, saison/episode optionnels."""
        return self._search(
            {
                "t": "tvsearch",
                "q": query,
                "imdbid": imdb_id,
                "tmdbid": tmdb_id,
                "season": str(season) if season is not None else None,
                "ep": str(ep) if ep is not None else None,
            }
        )
