# 5E — Layer stack

Trois plaques isométriques flottant l'une au-dessus de l'autre : la table brute, le modèle, la couche publiée.

- **Type** : symbole 3D
- **Police du wordmark** : Caprasimo
- **Fichiers** : `inline.html`, `mark-{dark|light}-{4a|4c|4e}.svg`
- **Palettes** : 4A acier & brume · 4C or & parchemin · 4E sauge & or

## Mise en œuvre

```html
<link rel="stylesheet" href="/brand/tokens.css">
<link rel="stylesheet" href="/brand/animations.css">
```

Deux façons de poser le symbole :

1. **SVG inline** (recommandé) — reprendre `inline.html`. Le symbole hérite des jetons `--sali-*`, change de mode et de palette sans recharger de fichier, et **c'est la seule forme qui accepte les animations**.
2. **Fichier statique** — `<img src="/brand/layer-stack/mark-dark-4a.svg" alt="SALI AI" width="32" height="32">`. Pratique pour un favicon, un e-mail ou un export bureautique ; aucune animation, et il faut choisir le fichier correspondant au mode.

## Clair / sombre

Le mode se pilote par un attribut sur `<html>` — rien à changer dans le balisage du logo :

```html
<html data-theme="dark" data-sali-palette="4a">
```

- `data-theme="dark"` : fond #131314, encre #e3e3e3, accent à pleine saturation.
- `data-theme="light"` : fond #f2f2f3, encre #1d1f20, et l'accent descend d'un cran (`--sali-deep`) — l'accent pur ne tient pas le contraste texte sur papier.
- Sans `data-theme`, `prefers-color-scheme` décide.

## Animation

À l'entrée, les plaques montent à leur position de bas en haut (90 ms d'écart) ; au survol, l'écart entre plaques s'ouvre de 4 px.

```html
<!-- à l'entrée : la classe suffit -->
<svg class="sali-mark sali-anim-stack">…</svg>

<!-- état « l'agent travaille » : ajouter is-working, retirer à la fin -->
el.classList.add('is-working');   // pendant l'analyse
el.classList.remove('is-working'); // rapport prêt
```

Tout est neutralisé sous `prefers-reduced-motion: reduce`.

## Tailles et garde-fous

- Symbole seul : 96 px (hero), 32 px (barre de nav, `.sali-mark--sm`), 16 px (favicon, `.sali-mark--xs`).
- Verrouillage horizontal en dessous de 320 px de large : garder le symbole seul.
- Zone de respect : un quart de la hauteur du symbole, minimum, sur les quatre côtés.
- Ne pas recolorer le symbole hors palettes, ne pas l'incliner, ne pas ajouter d'ombre portée (le relief est déjà dans le dégradé).

## Prompt d'intégration

```text
Intègre le logo SALI AI (variante 5E « Layer stack ») dans l'application.

Contexte : frontend Next.js, thème sombre par défaut (fond #131314, texte #e3e3e3),
un thème clair doit aussi être supporté.

À faire :
1. Copier le dossier export/ dans public/brand/ (tokens.css, animations.css, layer-stack/).
2. Importer tokens.css puis animations.css dans le layout racine, dans cet ordre.
3. Poser data-theme="dark" et data-sali-palette="4a" sur la balise <html> ; brancher
   data-theme sur le sélecteur de thème existant (valeurs : dark | light).
4. Créer un composant <SaliLogo size="sm|md|lg" animated working /> qui rend le balisage
   de layer-stack/inline.html. Ne pas remplacer les couleurs par des valeurs en dur :
   le symbole lit --sali-accent / --sali-ink / --sali-ground.
5. Utiliser <SaliLogo size="sm" /> dans la barre de navigation, size="lg" animated sur
   l'écran d'accueil, et passer working={true} pendant qu'une analyse tourne
   (la classe is-working suffit, elle est déjà stylée).
6. Favicon : layer-stack/mark-dark-4a.svg — vérifier la lisibilité à 16 px.
7. Charger la police Caprasimo (Google Fonts) et vérifier que le wordmark ne se coupe pas
   en dessous de 320 px : à cette largeur, n'afficher que le symbole.

Contraintes : aucune animation si prefers-reduced-motion: reduce ; aucune ombre portée
ajoutée au symbole ; respecter la zone de respect d'un quart de hauteur.
```
