# OCR des PDF scannés — cascade à trois moteurs

Un PDF sans couche texte (scan, photo) passe par
[`app/services/ocr_service.py`](app/services/ocr_service.py), qui tente trois
moteurs **dans l'ordre**. Le premier qui rend du texte gagne.

| # | Moteur | Exige | Qualité | Tableaux |
| --- | --- | --- | --- | --- |
| 1 | **Unlimited-OCR** | un serveur externe + GPU CUDA | la meilleure | markdown natif |
| 2 | **Transcription vision** | un modèle multimodal (Gemini, GPT-4o, Claude, llava…) | très bonne | markdown natif |
| 3 | **RapidOCR** | rien | correcte sur du texte net | reconstruits par géométrie, souvent inexploitables |

L'ordre ne classe pas les moteurs par qualité mais par **exigence** : chacun
demande moins que le précédent. Le dernier fonctionne sans GPU, sans réseau et
sans clé d'API — c'est le filet de sécurité.

Le texte reconnu réintègre le pipeline documentaire ordinaire (indexation
ChromaDB, résumé, citations). Une fois transcrit, le document est lisible par
**n'importe quel modèle texte, y compris un Ollama local** : c'est toute la
raison d'être de cette cascade.

> Il n'existe plus de session « visuelle ». L'indexation ColSmolVLM (retrieval
> par embeddings d'images) a été retirée : elle chargeait un modèle de 8 Go et
> tournait sur CPU, imposait un modèle vision à **chaque** question, et ne
> donnait pas de citations. La transcription en texte à l'upload rend le même
> service une seule fois, puis n'exige plus rien.

## Moteur 1 — Unlimited-OCR

[Unlimited-OCR](https://github.com/baidu/Unlimited-OCR) (Baidu) est un VLM de
*document parsing*. Il tourne dans un serveur séparé, joint par son API
OpenAI-compatible : aucune dépendance Python côté backend, et **aucun GPU requis
sur la machine qui sert l'API**.

### Démarrage

```bash
docker compose --profile ocr up
```

Le service `ocr` n'est pas dans le profil par défaut : il réclame un **GPU
NVIDIA** et une image de plusieurs Go. Sur GPU Hopper (CUDA 12.9), utiliser le
tag `vllm/vllm-openai:unlimited-ocr-cu129`.

Hors compose :

```bash
docker run --gpus all -p 10000:10000 vllm/vllm-openai:unlimited-ocr \
    --model baidu/Unlimited-OCR --served-model-name Unlimited-OCR \
    --max-model-len 32768 --port 10000
```

La [recette officielle](https://recipes.vllm.ai/baidu/Unlimited-OCR) fait foi
pour les options de service. Avec SGLang :

```bash
python -m sglang.launch_server \
    --model baidu/Unlimited-OCR --served-model-name Unlimited-OCR \
    --attention-backend fa3 --page-size 1 --mem-fraction-static 0.8 \
    --context-length 32768 --enable-custom-logit-processor \
    --disable-overlap-schedule --skip-server-warmup \
    --host 0.0.0.0 --port 10000
```

### Variables d'environnement

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `OCR_API_URL` | `http://localhost:10000/v1/chat/completions` | URL complète du point d'entrée. |
| `OCR_MODEL` | `Unlimited-OCR` | Doit correspondre au `--served-model-name`. |
| `OCR_TIMEOUT` | `1200` | Secondes, par page. |
| `OCR_LOGIT_PROCESSOR` | *(vide)* | Garde anti-répétition SGLang — voir ci-dessous. |

Sur les documents longs, SGLang évite les boucles de répétition avec un
*logit processor* dédié, qu'il attend sous forme de classe sérialisée :

```python
from sglang.srt.sampling.custom_logit_processor import DeepseekOCRNoRepeatNGramLogitProcessor
print(DeepseekOCRNoRepeatNGramLogitProcessor.to_str())
```

Le backend n'importe pas `sglang` (tout l'intérêt du chemin HTTP étant de ne rien
installer) : coller la chaîne obtenue dans `OCR_LOGIT_PROCESSOR` active la garde,
avec `ngram_size=35` et `window_size=128`. **Inutile avec vLLM**, dont la recette
la câble côté serveur.

### Détails

Une requête par page, mode image `gundam` (tuilage, meilleur sur les petits
caractères), 300 dpi, 8 pages de front. Le mode multi-pages en un appel n'est pas
utilisé : son format de sortie ne documente aucun séparateur de page, et le
deviner ferait reposer la numérotation — donc les citations RAG — sur une
heuristique. Les marqueurs `<|det|>…<|/det|>` sont retirés à la réception.

## Moteur 2 — transcription par le modèle vision

Les pages sont envoyées **au modèle multimodal déjà sélectionné par
l'utilisateur** (via `vision_service`, donc Gemini, OpenAI, Anthropic, Mistral,
Groq ou un modèle vision Ollama), avec pour seule consigne de transcrire en
markdown : mot à mot, dans la langue d'origine, tableaux compris.

Ce moteur pose son **propre prompt système**. Sans lui, `ask_vision` applique
celui de l'agent d'analyse de données, qui impose de conclure par des
suggestions d'analyses complémentaires : la transcription reviendrait enrobée de
commentaires, puis serait indexée telle quelle.

200 dpi, 4 pages de front (les API multimodales appliquent des quotas par
minute). Ignoré silencieusement si le modèle choisi n'est pas multimodal.

⚠️ Chaque page est un **appel d'API facturé**. Le plafond de 30 pages
(`MAX_OCR_PAGES`) borne autant le coût que la durée.

## Moteur 3 — RapidOCR

Moteur ONNX local (~15 Mo), sur CPU, sans dépendance système ni réseau. Le seul
qui fonctionne hors ligne dès `pip install`.

**Sur les tableaux, n'en attendez pas grand-chose.** RapidOCR ne rend que des
boîtes de texte avec leurs coordonnées ; la reconstruction est une heuristique
géométrique (`_table_depuis_geometrie`) qui retient la largeur de ligne la plus
fréquente et jette le reste. En échouent : les cellules fusionnées, les cellules
sur deux lignes, les tableaux noyés dans plus de texte courant que de lignes de
données, les scans inclinés, et les tableaux multi-pages (les en-têtes répétés
deviennent des lignes de données). Pour le **texte**, en revanche, c'est un filet
solide.

## Si les trois échouent

La session est créée quand même, avec un résumé qui explique lequel des trois
recours a manqué et quoi faire. Le chat n'aura aucun contenu sur lequel
s'appuyer : c'est assumé, perdre l'import serait plus pénible.

## Fonctionnement hors ligne

- **Moteur 3** : hors ligne dès l'installation.
- **Moteur 1** : hors ligne à l'exécution (`session.trust_env = False` neutralise
  même un proxy hérité de l'environnement), mais l'image Docker et les poids
  demandent un accès réseau **une fois**. Ensuite, `HF_HUB_OFFLINE=1` sur le
  service `ocr` verrouille le tout.
- **Moteur 2** : nécessite le réseau, sauf avec un modèle vision Ollama local
  (llava, llama3.2-vision…), auquel cas rien ne sort de la machine.

## Citation

```bibtex
@misc{yin2026unlimitedocrworks,
      title={Unlimited OCR Works},
      author={Youyang Yin and Huanhuan Liu and YY and Qunyi Xie and Chaorun Liu and Shiqi Yang and Shaohua Wang and Zhanlong Liu and Hao Zou and Jinyue Chen and Shu Wei and Jingjing Wu and Mingxin Huang and Zhen Wu and Guibin Wang and Tengyu Du and Lei Jia},
      year={2026},
      eprint={2606.23050},
      archivePrefix={arXiv},
      primaryClass={cs.CV},
      url={https://arxiv.org/abs/2606.23050},
}
```
