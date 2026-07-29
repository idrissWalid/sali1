# Prompt d'intégration — logo Sali AI

Copie-colle ce prompt à ton assistant de code (Claude Code, Cursor, Lovable…), avec le dossier `brand/` déposé à la racine du projet.

---

Intègre le nouveau logo « Sali AI » dans l'application. Les fichiers sont dans `brand/` :

- `sali-mark.svg` — le symbole en couleur (anneau sauge #7A8A5E, point terracotta #C67139)
- `sali-mark-mono.svg` — le symbole en `currentColor` (hérite de la couleur du texte parent)
- `sali-mark-onDark.svg` — anneau crème #F5EAD8, point terracotta — pour les fonds sombres
- `sali-mark-ink.svg` — tout en encre #201E1D — pour les impressions et les fonds clairs neutres
- `sali-favicon.svg` — le symbole dans un carré arrondi encre
- `sali-app-icon.svg` — le symbole dans un carré arrondi cacao #402310, pour l'icône d'app
- `sali-lockup.svg` — symbole + nom « Sali AI » + baseline « DATA INTELLIGENCE »

Tâches :

1. Déplace `brand/` dans `public/brand/` (ou l'équivalent dans ce projet) et déclare le favicon :
   `<link rel="icon" type="image/svg+xml" href="/brand/sali-favicon.svg">`
   plus `<link rel="apple-touch-icon" href="/brand/sali-app-icon.svg">`.
2. Crée un composant `SaliMark` qui inline le SVG (pas de `<img>`) et accepte `size` (px) et une couleur optionnelle. Par défaut il rend la version couleur ; en `mono` il rend `currentColor`.
3. Remplace le logo actuel de la barre d'en-tête par le chip existant contenant `SaliMark` à 32 px : fond crème `#F9F4ED` en thème sombre, fond encre `#201E1D` avec le symbole crème en thème clair. Le nom « Sali AI » à côté en Caprasimo 19 px.
4. Utilise `SaliMark` à 30 px comme avatar des réponses de l'assistant dans la discussion.
5. Indicateur de chargement : reprends l'anneau seul en rotation continue (2 s, linéaire) et laisse le point terracotta immobile en haut à droite.
6. Ajoute les polices : Caprasimo (nom de la marque uniquement) et Figtree (tout le reste), via Google Fonts.

Règles à respecter :

- Le point terracotta est toujours en haut à droite, jamais posé sur l'anneau, jamais d'une autre couleur que #C67139 (ou la couleur du texte en version mono).
- Marge libre autour du symbole égale au diamètre du point.
- Taille minimale : 18 px de haut.
- Ne pas étirer, ne pas incliner, ne pas ajouter d'ombre ou de dégradé.
- Ne pas utiliser le symbole comme puce décorative dans un paragraphe.

Palette de marque : terracotta #C67139 · sauge #7A8A5E · cacao #402310 · crème #F5EAD8 · encre #201E1D.
