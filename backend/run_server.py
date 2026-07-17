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

import torch
import uvicorn
from app.main import app
import logging

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
