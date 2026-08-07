# Sali AI — variante harmonisée

Cette variante conserve l'ambiance actuelle graphite, noire et lavande, ainsi que la structure trois panneaux.

## Changements

- Les dashboards utilisent désormais les surfaces, bordures, textes et accents de l'application principale.
- Les couleurs de graphiques proviennent d'une palette unique.
- Figtree devient la seule police produit ; Caprasimo reste réservé à la marque.
- Les composants shadcn et les composants historiques partagent les mêmes tokens sémantiques.
- Les boutons textuels ont une hauteur minimale de 44 px, un padding stable et peuvent grandir si leur libellé demande plus d'espace.

`app/design-system.css` est importé après `globals.css` et agit comme couche d'harmonisation sans modifier les flux ou la structure générale.
