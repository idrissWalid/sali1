# 3C — Lowercase serif

Aucun symbole : un bas-de-casse serif léger et resserré, « ai » collé au nom, filet tracé à la main dessous. Le moins « tech » du jeu.

- **Type** : wordmark seul
- **Police du wordmark** : Cormorant Garamond
- **Fichiers** : `inline.html` (le wordmark est du texte, pas un SVG)
- **Palettes** : 4A acier & brume · 4C or & parchemin · 4E sauge & or

## Mise en œuvre

```html
<link rel="stylesheet" href="/brand/tokens.css">
<link rel="stylesheet" href="/brand/animations.css">
```

## Clair / sombre

Le mode se pilote par un attribut sur `<html>` — rien à changer dans le balisage du logo :

```html
<html data-theme="dark" data-sali-palette="4a">
```

- `data-theme="dark"` : fond #131314, encre #e3e3e3, accent à pleine saturation.
- `data-theme="light"` : fond #f2f2f3, encre #1d1f20, et l'accent descend d'un cran (`--sali-deep`) — l'accent pur ne tient pas le contraste texte sur papier.
- Sans `data-theme`, `prefers-color-scheme` décide.

## Animation

Le filet se dessine de gauche à droite en 700 ms après l'apparition du mot ; au survol il se redessine.

```html
<!-- à l'entrée : la classe suffit -->
<svg class="sali-mark sali-anim-rule">…</svg>

<!-- état « l'agent travaille » : ajouter is-working, retirer à la fin -->
el.classList.add('is-working');   // pendant l'analyse
el.classList.remove('is-working'); // rapport prêt
```

Tout est neutralisé sous `prefers-reduced-motion: reduce`.

## Tailles et garde-fous

- Symbole seul : 96 px (hero), 32 px (barre de nav, `.sali-mark--sm`), 16 px (favicon, `.sali-mark--xs`).
- Verrouillage horizontal en dessous de 320 px de large : garder le symbole seul.
- Zone de respect : un quart de la hauteur du symbole, minimum, sur les quatre côtés.
- Ne pas recolorer le symbole hors palettes, ne pas l'incliner, ne pas ajouter d'ombre portée.

## Prompt d'intégration

```text
Intègre le logo SALI AI (variante 3C « Lowercase serif ») dans l'application.

Contexte : frontend Next.js, thème sombre par défaut (fond #131314, texte #e3e3e3),
un thème clair doit aussi être supporté.

À faire :
1. Copier le dossier export/ dans public/brand/ (tokens.css, animations.css, lowercase-serif/).
2. Importer tokens.css puis animations.css dans le layout racine, dans cet ordre.
3. Poser data-theme="dark" et data-sali-palette="4a" sur la balise <html> ; brancher
   data-theme sur le sélecteur de thème existant (valeurs : dark | light).
4. Créer un composant <SaliLogo size="sm|md|lg" animated working /> qui rend le balisage
   de lowercase-serif/inline.html. Ne pas remplacer les couleurs par des valeurs en dur :
   le symbole lit --sali-accent / --sali-ink / --sali-ground.
5. Utiliser <SaliLogo size="sm" /> dans la barre de navigation, size="lg" animated sur
   l'écran d'accueil, et passer working={true} pendant qu'une analyse tourne
   (la classe is-working suffit, elle est déjà stylée).
6. Favicon : exporter le badge « S » en 32×32 et 16×16 — vérifier la lisibilité à 16 px.
7. Charger la police Cormorant Garamond (Google Fonts) et vérifier que le wordmark ne se coupe pas
   en dessous de 320 px : à cette largeur, n'afficher que le symbole.

Contraintes : aucune animation si prefers-reduced-motion: reduce ; aucune ombre portée
ajoutée au symbole ; respecter la zone de respect d'un quart de hauteur.
```
