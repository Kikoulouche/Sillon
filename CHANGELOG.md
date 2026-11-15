# Changelog

Les versions suivent [SemVer](https://semver.org/lang/fr/). Les mises à jour automatiques de yt-dlp
(publiées chaque lundi si besoin) incrémentent le dernier chiffre.

## 1.0.3 — 2026-11-15

- Nouveau logo, lisible dans la barre des tâches (claire ou sombre) : vinyle noir sur fond ambre,
  petites tailles dessinées à part.
- Barre des tâches : l'app installée n'apparaît plus avec une icône différente de son raccourci.

## 1.0.2 — 2026-11-15

- Mises à jour : l'installation automatique à la fermeture de l'app ne se lançait pas (corrigé).
  Les versions 1.0.0 et 1.0.1 téléchargent la mise à jour mais ne l'installent pas : réinstaller une fois avec `install.ps1`.
- Téléchargement : nouvel essai automatique quand YouTube renvoie une erreur passagère (403/429).
- Plus d'erreur dans le journal quand on ferme l'app pendant une tâche.

## 1.0.1 — 2026-11-15

- Script d'installation : messages lisibles dans toutes les consoles Windows.
- GitHub Actions : passage à `actions/checkout@v5` et `actions/setup-python@v6`.

## 1.0.0 — 2026-11-15

Première version.

- Recherche YouTube avec miniatures, file d'attente, téléchargement en M4A (AAC) avec titre, artiste et pochette.
- Envoi direct dans VLC sur l'iPhone, en USB, sans iTunes Sync.
- Scan de l'iPhone : affiche tout ce qui est dans VLC, même depuis un autre PC, et permet de le supprimer.
- Anti-doublons : les morceaux déjà sur le PC ou l'iPhone sont signalés dans la recherche.
- Mises à jour automatiques via GitHub Releases.
