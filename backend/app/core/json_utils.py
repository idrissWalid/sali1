"""json_utils.py — Sérialisation JSON tolérante aux flottants non finis.

`NaN`, `Infinity` et `-Infinity` ne font pas partie du JSON standard. Python les
accepte pourtant des deux côtés :
  - `json.dumps` les écrit tels quels (`allow_nan=True` par défaut) ;
  - `json.loads` les relit sans broncher.

Un `NaN` produit par pandas/statsmodels traverse donc silencieusement le sandbox
puis SQLite, et n'explose qu'au dernier moment : Starlette sérialise ses réponses
avec `allow_nan=False` et lève alors
`ValueError: Out of range float values are not JSON compliant`.

On convertit ces valeurs en `null`, seule représentation JSON valide d'une donnée
manquante — et celle que `JSON.parse` côté navigateur sait lire.
"""

import json
import math
from typing import Any

from starlette.responses import JSONResponse


def json_safe(obj: Any) -> Any:
    """Remplace récursivement les flottants non finis par `None`.

    Les `float` numpy (`np.float64`) héritent de `float` et sont donc couverts.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def dumps_safe(obj: Any, **kwargs: Any) -> str:
    """`json.dumps` qui ne peut pas écrire de JSON invalide.

    À utiliser avant toute persistance en base : sans ça, un `NaN` est stocké
    littéralement et fait échouer la lecture de la ligne, longtemps après coup.
    """
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(json_safe(obj), allow_nan=False, **kwargs)


class SafeJSONResponse(JSONResponse):
    """Réponse JSON qui neutralise les flottants non finis.

    Le chemin nominal est identique à `JSONResponse` : on ne paie le coût du
    parcours récursif que lorsqu'une valeur non finie est effectivement présente.
    """

    def render(self, content: Any) -> bytes:
        try:
            return self._dump(content)
        except ValueError:
            return self._dump(json_safe(content))

    @staticmethod
    def _dump(content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")
