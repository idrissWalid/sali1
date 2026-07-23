from app.services.gemini_service import complete_text

INTENT_PROMPT = """Classifie la demande suivante en UN SEUL MOT parmi ces options :
- visualisation : l'utilisateur veut un graphique, une courbe, une distribution visuelle, un diagramme, un plot
- ml : l'utilisateur veut un modèle, une prédiction, un clustering, une classification, une régression, une détection d'anomalies
- rapport : l'utilisateur veut générer, exporter, télécharger un rapport, un document PDF ou Word
- stat_descriptive : l'utilisateur demande des statistiques descriptives — moyenne, médiane, écart-type, min, max, quartiles, variance, corrélation, valeurs manquantes, fréquences, résumé statistique, describe
- analyse : l'utilisateur veut une analyse approfondie, des tendances, des insights, des comparaisons complexes
- series_temporelles : l'utilisateur veut analyser une évolution dans le temps, faire une prévision temporelle, un forecast, ou isoler des données temporelles
- conversation : l'utilisateur pose une question générale, fait un commentaire, ou demande une explication

Réponds UNIQUEMENT par un seul mot parmi la liste ci-dessus, sans ponctuation ni explication.

Demande : "{message}"
"""

def detect_intent(message: str, model: str = "gemma2:latest") -> str:
    try:
        prompt = INTENT_PROMPT.format(message=message)
        response_text = complete_text(prompt, model)

        intent = response_text.strip().lower().replace(".", "").replace("\n", "")
        valid = {"visualisation", "ml", "rapport", "stat_descriptive", "analyse", "series_temporelles", "conversation"}
        return intent if intent in valid else "conversation"
    except Exception:
        return "conversation"
