"""Les prompts doivent être CONSTRUITS dans le budget du modèle, pas coupés après.

`ollama_service._trim_prompt` raccourcit en aval, au milieu du prompt : sur un
contexte de données, la coupe tombe au hasard dans un JSON et fait disparaître les
statistiques auxquelles les consignes finales se réfèrent encore.

Mesuré sur le corpus réel de `data/uploads` (24 fichiers profilés), le poste
dominant n'était pas les statistiques (12,9 %) mais l'aperçu des 5 premières lignes
(83,5 %) : 17 836 caractères de corps d'articles, rejoués à CHAQUE tour de chat
puisque `get_data_context` est reconstruit à chaque message.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.prompt_budget import (
    LARGEUR_MAX_CELLULE,
    PROFIL_API,
    PROFIL_LOCAL,
    apercu_borne,
    apercu_dans_budget,
    bloc_apercu,
    est_local,
    profil_modele,
    stats_essentielles,
)


class TestProfil:
    @pytest.mark.parametrize("model", [
        "qwen3.5:4b", "gemma2:latest", "llava:13b", "mistral:7b",
    ])
    def test_un_nom_nu_est_un_modele_local(self, model):
        assert est_local(model)
        assert profil_modele(model) is PROFIL_LOCAL

    @pytest.mark.parametrize("model", [
        "gemini-3.1-flash-lite-preview",
        "openai/gpt-4o", "anthropic/claude-sonnet-4-5",
        "mistral/mistral-large-latest", "groq/llama-3.3-70b-versatile",
    ])
    def test_un_prefixe_fournisseur_ou_gemini_est_distant(self, model):
        assert not est_local(model)
        assert profil_modele(model) is PROFIL_API

    @pytest.mark.parametrize("model", [None, "", "   "])
    def test_un_modele_absent_est_traite_comme_distant(self, model):
        """C'est le défaut de l'application. Surestimer le budget d'un modèle local
        se paie en raccourcissement ; le sous-estimer priverait une API de contexte
        sans raison."""
        assert profil_modele(model) is PROFIL_API

    def test_seul_le_local_renonce_aux_consignes_denses(self):
        """`consignes_denses` gouverne le routage des méthodologies multi-étapes
        (SARIMA A–H). Une API, même petite, sait les suivre — la dégrader pour tout
        le monde casserait le chemin produit par défaut."""
        assert PROFIL_API.consignes_denses
        assert not PROFIL_LOCAL.consignes_denses
        assert PROFIL_LOCAL.budget_contexte < PROFIL_API.budget_contexte


class TestApercuBorne:
    def test_les_cellules_longues_sont_ecourtees_et_signalees(self):
        [ligne] = apercu_borne([{"text": "x" * 5_000}])

        assert len(ligne["text"]) < 5_000
        # La marque évite que le modèle prenne la valeur coupée pour la vraie.
        assert "écourtée" in ligne["text"]
        assert ligne["text"].startswith("x" * LARGEUR_MAX_CELLULE)

    def test_les_valeurs_non_textuelles_sont_intactes(self):
        """Les convertir en texte pour les mesurer changerait le type que le modèle
        lit dans le JSON — une numérique deviendrait une catégorielle."""
        origine = {"n": 42, "ratio": 3.14, "actif": True, "vide": None}
        [ligne] = apercu_borne([origine])

        assert ligne == origine

    def test_une_cellule_courte_nest_pas_touchee(self):
        [ligne] = apercu_borne([{"region": "Nord", "date": "2018-08-29 10:44:48"}])

        assert ligne == {"region": "Nord", "date": "2018-08-29 10:44:48"}


class TestApercuDansBudget:
    def test_des_lignes_sont_retirees_jamais_des_colonnes(self):
        """Une ligne en moins reste un exemple complet de la structure. Une colonne
        en moins ferait croire au modèle qu'elle n'existe pas."""
        preview = [{"a": "x" * 300, "b": "y" * 300, "c": 1} for _ in range(5)]

        lignes, retirees = apercu_dans_budget(preview, budget=700)

        assert retirees == len(preview) - len(lignes)
        assert lignes, "au moins une ligne doit survivre à ce budget"
        # Toutes les colonnes sont encore là dans les lignes conservées.
        assert all(set(ligne) == {"a", "b", "c"} for ligne in lignes)
        assert len(json.dumps(lignes, ensure_ascii=False, indent=2)) <= 700

    def test_un_apercu_qui_tient_deja_est_inchange(self):
        preview = [{"region": "Nord", "montant": 12}]

        lignes, retirees = apercu_dans_budget(preview, budget=10_000)

        assert lignes == preview
        assert retirees == 0

    def test_le_budget_est_respecte_meme_sur_le_pire_cas(self):
        preview = [{"text": "z" * 20_000} for _ in range(5)]

        lignes, _ = apercu_dans_budget(preview, budget=1_000)

        rendu = json.dumps(lignes, ensure_ascii=False, indent=2)
        assert len(rendu) <= 1_000

    def test_une_table_large_garde_un_exemple_en_resserrant_la_largeur(self):
        """À 13 colonnes toutes textuelles, une ligne bornée à 200 caractères pèse
        déjà plus que le budget d'un modèle local. Plutôt que de supprimer l'aperçu
        en entier, la largeur se resserre : une ligne étroite reste un exemple
        complet de la structure, et le modèle apprend au moins la forme de chaque
        colonne."""
        preview = [{f"c{i}": "texte long. " * 300 for i in range(13)} for _ in range(5)]

        lignes, _ = apercu_dans_budget(preview, budget=PROFIL_LOCAL.budget_contexte // 3)

        assert lignes, "l'aperçu ne doit pas être supprimé en entier"
        # Toutes les colonnes sont représentées dans la ligne conservée.
        assert set(lignes[0]) == {f"c{i}" for i in range(13)}
        # Et le resserrement a bien eu lieu : plus étroit que le plafond nominal.
        assert len(lignes[0]["c0"]) < LARGEUR_MAX_CELLULE + len("… [valeur écourtée]")


class TestBlocApercu:
    def test_les_lignes_retirees_sont_annoncees(self):
        """Sans mention, un aperçu de deux lignes se lit comme un fichier de deux
        lignes."""
        preview = [{"a": "x" * 400} for _ in range(5)]

        bloc = bloc_apercu(preview, budget=600)

        assert "retirée" in bloc
        assert "sur 5" in bloc

    def test_un_apercu_entierement_omis_le_dit(self):
        bloc = bloc_apercu([{"a": "x" * 5_000} for _ in range(5)], budget=50)

        assert "omis" in bloc
        # Et il renvoie le modèle vers ce qui reste exploitable.
        assert "statistiques" in bloc

    def test_un_apercu_absent_ne_produit_pas_un_json_vide(self):
        assert bloc_apercu(None, budget=1_000) == "Aucun aperçu disponible."
        assert bloc_apercu([], budget=1_000) == "Aucun aperçu disponible."

    def test_un_apercu_qui_tient_est_rendu_sans_mention(self):
        bloc = bloc_apercu([{"region": "Nord"}], budget=10_000)

        assert "retirée" not in bloc
        assert "omis" not in bloc
        assert json.loads(bloc) == [{"region": "Nord"}]


class TestStatsEssentielles:
    def test_les_statistiques_decoratives_sont_retirees(self):
        """`get_data_context` versait le dump ydata-profiling intégral à CHAQUE
        tour, là où `build_analysis_prompt` filtrait déjà. Un seul filtre pour les
        deux."""
        variables = {
            "montant": {
                "type": "Numeric", "moyenne": 12.5, "ecart_type": 3.1,
                "histogramme": list(range(500)), "quantiles_fins": {"0.001": 1},
            },
        }

        reduit = stats_essentielles(variables)

        assert reduit["montant"] == {"type": "Numeric", "moyenne": 12.5, "ecart_type": 3.1}

    def test_supporte_labsence_de_statistiques(self):
        assert stats_essentielles(None) == {}
        assert stats_essentielles({}) == {}


class TestPromptDAnalyseReel:
    """Le cas mesuré qui motive tout ce module : un jeu de données textuel dont
    l'aperçu, seul, dépassait le budget d'un modèle local."""

    @staticmethod
    def _profil_et_stats():
        return (
            {
                "rows": 166, "columns": 3,
                "column_names": ["author", "text", "publishedAt"],
                "preview": [
                    {"author": "ABC News", "text": "corps d'article. " * 300,
                     "publishedAt": "2018-08-29 10:44:48"}
                    for _ in range(5)
                ],
                "duplicates": 0,
            },
            {
                "dataset_overview": {"n_doublons": 0},
                "variables": {"author": {"type": "Categorical", "n_valeurs_distinctes": 12}},
                "missing": {},
                "correlations": {},
            },
        )

    def test_le_prompt_local_tient_dans_le_budget_ollama(self):
        from app.services.analysis_service import build_analysis_prompt
        from app.services.ollama_service import MAX_PROMPT_CHARS

        profile, stats = self._profil_et_stats()
        prompt = build_analysis_prompt(profile, stats, model="qwen3.5:4b")

        assert len(prompt) <= MAX_PROMPT_CHARS
        # Les consignes finales — celles que la coupe aveugle épargnait mais dont
        # elle supprimait les données — sont bien là.
        assert "PROPOSITIONS" in prompt
        assert "RÉSUMÉ" in prompt

    def test_la_structure_reste_lisible_apres_bornage(self):
        """Borner ne doit pas coûter la connaissance du schéma."""
        from app.services.analysis_service import build_analysis_prompt

        profile, stats = self._profil_et_stats()
        prompt = build_analysis_prompt(profile, stats, model="qwen3.5:4b")

        for colonne in ("author", "text", "publishedAt"):
            assert colonne in prompt
        assert "2018-08-29 10:44:48" in prompt      # une date entière, non coupée

    def test_le_prompt_local_ne_depasse_jamais_celui_dune_api(self):
        """Sur une table étroite, borner les cellules suffit : les deux profils
        reçoivent alors le même prompt. Le retrait de lignes est l'exception, pas la
        règle — d'où une inégalité large."""
        from app.services.analysis_service import build_analysis_prompt

        profile, stats = self._profil_et_stats()
        local = build_analysis_prompt(profile, stats, model="qwen3.5:4b")
        api = build_analysis_prompt(profile, stats, model="gemini-3.1-flash-lite-preview")

        assert len(local) <= len(api)

    def test_sur_une_table_large_le_local_recoit_strictement_moins(self):
        """C'est la forme du cas réel mesuré (`fb_articles`, 13 colonnes dont
        plusieurs textuelles) : 21 373 caractères avant, dont 83,5 % d'aperçu."""
        from app.services.analysis_service import build_analysis_prompt
        from app.services.ollama_service import MAX_PROMPT_CHARS

        profile = {
            "rows": 166, "columns": 13, "duplicates": 0,
            "column_names": [f"col{i}" for i in range(13)],
            "preview": [{f"col{i}": "corps d'article. " * 300 for i in range(13)}
                        for _ in range(5)],
        }
        stats = {"dataset_overview": {}, "variables": {}, "missing": {}, "correlations": {}}

        local = build_analysis_prompt(profile, stats, model="qwen3.5:4b")
        api = build_analysis_prompt(profile, stats, model="gemini-3.1-flash-lite-preview")

        assert len(local) < len(api)
        assert len(local) <= MAX_PROMPT_CHARS
