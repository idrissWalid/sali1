# Sali AI — variante redesign

Cette variante pousse l'identité Sali au premier plan sans changer les flux métier.

## Direction

- Palette chaude : encre, cacao, crème, sauge et terracotta.
- Deux familles seulement : Figtree pour le produit, Caprasimo pour la marque.
- Accueil plus éditorial et CTA d'import clairement prioritaire.
- Dashboards rattachés au même langage que l'espace Chat / Données / Studio.
- KPIs traités comme une bande d'information plutôt qu'une accumulation de cartes.

## Système

`app/design-system.css` suit trois couches : primitives de marque, tokens sémantiques puis contrats de composants. Il est importé après `globals.css` afin de conserver la logique existante tout en servant de source de vérité visuelle à toutes les routes.

## Boutons

Les actions textuelles utilisent une hauteur minimale de 44 px, un padding horizontal stable, un line-height de 1.25 et peuvent augmenter en hauteur au lieu de comprimer leur libellé. Les contrôles purement iconographiques gardent leur taille carrée.
