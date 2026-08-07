from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# Charger le modèle NLLB de Meta
model_id = "facebook/nllb-200-distilled-600M"
tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForSeq2SeqLM.from_pretrained(model_id)

# Définir les langues source et cible
src_lang = "fra_Latn"
tgt_lang = "mos_Latn"

# Préparer la phrase à traduire
text_to_translate = "du riz et du mil"

# Définir la langue source pour le tokenizer
tokenizer.src_lang = src_lang
inputs = tokenizer(text_to_translate, return_tensors="pt")

# Traduire la phrase en spécifiant le token de début de phrase forcé pour la langue cible
# Le token BOS de la langue cible est nécessaire pour NLLB
forced_bos_token_id = tokenizer.convert_tokens_to_ids(tgt_lang)
outputs = model.generate(**inputs, forced_bos_token_id=forced_bos_token_id)

translated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

print(f"Original ({src_lang}): {text_to_translate})")
print(f"Traduction ({tgt_lang}): {translated_text})")