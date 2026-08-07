# SALI AI — jeu de logos, mode clair/sombre et animations

Onze marques retenues, prêtes à tester. Ouvrir **preview.html** dans un navigateur :
deux boutons en haut à droite basculent le mode (sombre / clair) et la palette (4A / 4C / 4E),
et chaque carte permet de rejouer l'animation d'entrée ou de simuler l'état « analyse en cours ».

## Contenu

| Dossier | Réf. | Nom | Type |
| --- | --- | --- | --- |
| `resolve/` | 1B | Resolve | symbole + wordmark |
| `s-bars/` | 1C | S-bars | monogramme |
| `wordart-pill/` | 2A | Wordart pill | wordmark seul |
| `ribbon-s/` | 2B | Ribbon S | symbole |
| `soft-stack/` | 2C | Soft stack | symbole |
| `rosette/` | 3B | Rosette | symbole |
| `lowercase-serif/` | 3C | Lowercase serif | wordmark seul |
| `wave-diamond/` | 3E | Wave diamond | symbole |
| `brushed-s/` | 5A | Brushed S | symbole 3D |
| `ribbon-rosette/` | 5C | Ribbon rosette | symbole 3D |
| `layer-stack/` | 5E | Layer stack | symbole 3D |

Chaque dossier contient :

- `INTEGRATION.md` — la fiche de pose **et le prompt d'intégration** à coller tel quel dans un agent de code.
- `inline.html` — le balisage à copier (SVG inline + wordmark). C'est la forme qui accepte les animations.
- `mark-{dark|light}-{4a|4c|4e}.svg` — six fichiers statiques par marque (favicon, e-mail, bureautique).
  Les deux wordmarks (2A, 3C) n'en ont pas : ce sont du texte.

À la racine :

- `tokens.css` — couleurs, polices, tailles et verrouillages. La seule feuille obligatoire.
- `animations.css` — les onze animations, toutes neutralisées sous `prefers-reduced-motion`.
- `preview.html` — la planche de test.

## Modes

Le mode et la palette sont deux attributs sur `<html>` ; le balisage du logo ne change pas.

```html
<html data-theme="dark" data-sali-palette="4a">
```

- **Sombre** — fond #131314, encre #e3e3e3, accent à pleine saturation. C'est le mode natif du produit.
- **Clair** — fond #f2f2f3, encre #1d1f20, accent descendu d'un cran (`--sali-deep`) : l'accent pur ne
  tient pas le contraste à taille de texte sur papier.
- Sans `data-theme`, `prefers-color-scheme` décide.

## Palettes

| Réf. | Nom | Accent | Second |
| --- | --- | --- | --- |
| 4A | Acier & brume | #5980A6 | #B0C4D8 |
| 4C | Or & parchemin | #B68235 | #E3D5B4 |
| 4E | Sauge & or | #7A8A5E | #B68235 |

## Polices

Barlow Condensed (1B, 1C), Caprasimo (2A, 2B, 2C, 3B, 5E), Cormorant Garamond (3C, 5A, 5C) —
toutes sur Google Fonts. `preview.html` les charge déjà.

## Limites à connaître

- Les animations exigent un SVG **inline** ; un `<img src="mark.svg">` ne les reçoit pas.
- 5A, 5C et 5E reposent sur des dégradés et un filtre : parfaits à l'écran, à remplacer par la version
  plate (1C, 3B, 3E) pour une impression en une couleur ou une gravure.
- Les identifiants de dégradés sont fixes dans `inline.html` : si tu poses deux fois la même marque
  dimensionnelle sur une page, suffixe les `id` pour éviter la collision.
