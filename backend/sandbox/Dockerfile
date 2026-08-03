FROM python:3.11-slim

# Sécurité : utilisateur non-root
RUN groupadd -r sandbox && useradd -r -g sandbox sandbox

WORKDIR /app

# Installer libgomp1 pour OpenMP (scikit-learn / OpenBLAS)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copier les dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Couche séparée : ajouter une dépendance ici ne réinstalle pas toute la base.
COPY requirements-forecast.txt .
RUN pip install --no-cache-dir --timeout 120 --retries 10 -r requirements-forecast.txt

# Idem pour le tournoi supervisé, en dernier : c'est la couche la plus susceptible
# d'évoluer, la placer ici garde les deux précédentes en cache.
COPY requirements-supervised.txt .
RUN pip install --no-cache-dir --timeout 120 --retries 10 -r requirements-supervised.txt

# Copier le runner
COPY runner.py .

# Répertoires temporaires pour graphiques et config matplotlib
RUN mkdir -p /tmp/sandbox /tmp/mpl_config && chown sandbox:sandbox /tmp/sandbox /tmp/mpl_config

# Config matplotlib pour éviter les warnings
ENV MPLCONFIGDIR=/tmp/mpl_config

# Passer en utilisateur non-root
USER sandbox

# Point d'entrée : lecture depuis stdin, écriture vers stdout
CMD ["python", "runner.py"]
