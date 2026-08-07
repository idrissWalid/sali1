import os

# Bannière promotionnelle « Upgrade to ydata-sdk » imprimée à l'import de
# ydata-profiling, une fois par processus (donc deux fois avec le reloader).
# La bibliothèque prévoit cette variable pour la taire ; à définir AVANT que
# `app.main` n'importe le profiling.
os.environ.setdefault("YDATA_SUPPRESS_BANNER", "1")

import ssl
import certifi

# Patch SSLContext to prevent Windows ASN.1 certificate store loading issues
orig_load_default_certs = ssl.SSLContext.load_default_certs

def patched_load_default_certs(self, *args, **kwargs):
    try:
        return orig_load_default_certs(self, *args, **kwargs)
    except Exception:
        return self.load_verify_locations(cafile=certifi.where())

ssl.SSLContext.load_default_certs = patched_load_default_certs

import uvicorn
from app.main import app
import logging

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

if __name__ == "__main__":
    # `reload=True` surveillait tout `backend/`, venvs compris (~200 000 fichiers
    # entre venv/ et .venv-timecopilot/) alors que la limite système par défaut
    # est de 65 536 watchers inotify. Le watcher épuisait le quota, et webpack
    # côté frontend n'en obtenait plus aucun : « ENOSPC: System limit for number
    # of file watchers reached » en boucle. On ne surveille donc que le code.
    #
    # Host et port surchargeables par l'environnement (dev.ps1 -BackendPort),
    # sans quoi deux instances ne peuvent pas cohabiter. Défauts inchangés.
    uvicorn.run(
        "app.main:app",
        host=os.getenv("BACKEND_HOST", "127.0.0.1"),
        port=int(os.getenv("BACKEND_PORT", "8000")),
        reload=True,
        reload_dirs=["app"],
    )
