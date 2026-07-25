from app.services.sandbox_service import execute_code, validate_output
from app.services.gemini_service import complete_text
from app.services.model_specs import ModelSpec
from app.core import config

MAX_ATTEMPTS = 3

def run_with_autocorrect(
    initial_code: str,
    file_bytes: bytes,
    filename: str,
    question: str,
    data_context: str,
    spec: ModelSpec = None,
    model: str | None = None
) -> dict:
    """
    Exécute le code, et si erreur ou résultats suspects,
    demande à Gemini de corriger et relance. Max 3 tentatives.
    Retourne : { output, images, error, attempts }
    """
    model = model or config.get_default_model()
    code = initial_code
    last_result = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = execute_code(code, file_bytes, filename)
        
        # Validation ML si spec fourni
        if spec:
            result = validate_output(result, spec)

        last_result = result
        last_result["attempts"] = attempt

        # Succès sans erreur
        if not result["error"]:
            # Vérifier si le résultat semble vide ou suspect
            if not result["output"].strip() and not result["images"]:
                # Rien produit — on demande à Gemini d'ajuster
                code = _ask_correction(
                    code=code,
                    question=question,
                    data_context=data_context,
                    error_msg="Le code s'est exécuté sans erreur mais n'a produit aucune sortie ni graphique.",
                    model=model,
                )
                continue
            # Résultat valide
            break

        # Erreur — demander correction si pas dernier essai
        if attempt < MAX_ATTEMPTS:
            code = _ask_correction(
                code=code,
                question=question,
                data_context=data_context,
                error_msg=result["error"]["technical"],
                model=model,
                spec=spec,
            )

    return last_result


def _ask_correction(code: str, question: str, data_context: str, error_msg: str, model: str | None = None, spec: ModelSpec = None) -> str:
    model = model or config.get_default_model()
    # Réinjecte la méthodologie/le squelette complet (spec.prompt_fragment), pas
    # seulement l'erreur : sinon une correction ponctuelle "répare" le bug signalé
    # mais peut faire régresser d'autres parties de la méthodologie (ex. gates
    # ou clés obligatoires) qui ne sont plus sous les yeux du modèle.
    methodology_reminder = f"\nRAPPEL DE LA MÉTHODOLOGIE À RESPECTER INTÉGRALEMENT (ne régresse sur aucun point ci-dessous en corrigeant) :\n{spec.prompt_fragment}\n" if spec else ""
    prompt = f"""
Tu as généré ce code Python pour répondre à : "{question}"

{data_context}

CODE EXÉCUTÉ :
{code}

ERREUR OU PROBLÈME DÉTECTÉ :
{error_msg}
{methodology_reminder}
Corrige le code pour résoudre ce problème précis, SANS supprimer ni simplifier les autres étapes de la méthodologie ci-dessus (toutes les clés obligatoires de metrics.json doivent rester présentes).
Le dataframe est dans la variable `df`.
Réponds UNIQUEMENT avec le code Python corrigé, sans explication ni markdown.
"""
    try:
        corrected = complete_text(prompt, model).strip()

        if corrected.startswith("```"):
            lines = corrected.split("\n")
            corrected = "\n".join(lines[1:-1])
        return corrected
    except Exception:
        return code  # retourne le code original si Gemini échoue
