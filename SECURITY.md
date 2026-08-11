# Security Policy

## Supported versions

Seule la derniere version de `main` recoit des correctifs de securite (pas
encore de releases etiquetees).

| Version          | Supported          |
| ---------------- | ------------------ |
| `main` (HEAD)    | :white_check_mark: |
| Versions ant.    | :x:                |

## Reporting a Vulnerability

Ne pas ouvrir d'issue publique. Signaler en prive :

- **GitHub** : "Report a vulnerability" de l'onglet Security du depot
  (https://github.com/ICCUser/nfogen/security/advisories/new).
- A defaut : issue vide demandant un canal prive, ou contact via le profil
  GitHub du mainteneur.

### A inclure

- Impact (attaquant non authentifie ? privilege admin requis ?).
- Etapes de reproduction (commande, payload, versions, variables d'env pertinentes).
- Mode de deploiement vise (instance ouverte / token / comptes nommes / frontend servi par l'API).

### Delais

- Accuse de reception : 7 jours.
- Avancement : au moins tous les 14 jours.
- Decision (accepte/infos complementaires/decline) : sous 30 jours.

## Posture de securite

nfogen est concu pour plusieurs administrateurs d'un meme tracker (un seul
role "admin"). Composants sensibles :

- **Authentification** : token API partage (`NFOGEN_API_TOKEN`) et/ou comptes
  nommes (`NFOGEN_ACCOUNTS_FILE`), sessions en cookie `httpOnly` (jamais en
  `localStorage`), mots de passe en PBKDF2-HMAC-SHA256 comparees en temps
  constant, throttle anti-bruteforce par compte (5 essais / 30 s).
- **Generation ouverte par defaut** : `/generate`, `/generate/json` et
  `/propose-name` ne sont proteges que si `NFOGEN_REQUIRE_AUTH_FOR_GENERATE=1`
  est defini. Activez-le sur une instance exposee publiquement.
- **Profils administrateur** : un `rules.json` est fourni par un admin de
  confiance ; les motifs regex qu'il contient sont executes via RE2 (moteur a
  automate, temps lineaire garanti, aucun backtracking exponentiel possible
  par construction), aussi bien a l'ecriture/import du profil qu'a chaque
  generation (protection ReDoS, cf. `nfogen/rules.py`).
- **Templates** : rendus dans un `SandboxedEnvironment` Jinja2 (dependance
  `jinja2>=3.1.6`, qui corrige des contournements de sandbox publics).

L'historique des correctifs de securite figure dans `ROADMAP.md` (section
"Audit securite") et dans le `git log`.
