# Security Policy

## Supported versions

Seule la derniere version de la branche `main` recoit des correctifs de
securite. nfogen est un projet jeune (pas encore de releases etiquetees) :
utilisez le code a jour de `main`, ou le paquet publie le plus recent.

| Version          | Supported          |
| ---------------- | ------------------ |
| `main` (HEAD)    | :white_check_mark: |
| Versions ant.    | :x:                |

## Reporting a Vulnerability

Merci de NE PAS ouvrir une issue publique pour une vulnerabilite. Signalez-la
en prive afin qu'on puisse la corriger avant toute divulgation :

- **GitHub** : outil "Report a vulnerability" de l'onglet **Security** du depot
  (https://github.com/ICCUser/nfogen/security/advisories/new), voie privilegiee.
- A defaut : ouvrez une issue *vide* demandant un canal de contact prive, ou
  contactez le mainteneur via son profil GitHub.

### Ce qu'inclure dans le signalement

- Description du probleme et de son impact (attaquant non authentifie ?
  privilege admin requis ?).
- Etapes minimales pour le reproduire (commande `curl`, payload, version de
  Python / du navigateur, variables d'environnement pertinentes).
- Le mode de deploiement vise (instance ouverte / protegee par token /
  comptes nommes / frontend servi par l'API).

### Calendre de reponse

- **Accuse de reception** : sous 7 jours.
- **Mise a jour d'avancement** : au moins tous les 14 jours jusqu'a resolution.
- **Decision** : accepte (correctif en cours + credit au rapporteur dans
  l'advisory), demande d'informations complementaires, ou decline (avec
  justification) -- en principe dans les 30 jours.

## Posture de securite

nfogen est concu pour etre operable par plusieurs administrateurs d'un **meme**
tracker (un seul role "admin"). Les composants sensibles sont :

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
