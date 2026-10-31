# WebGIS de suivi des plantations — Louga–Bandegne

Prototype fonctionnel développé dans le cadre d'un mémoire de Master 2
(Université Amadou Mahtar Mbow, 2026).

## Contenu du dépôt

- `streamlit_app.py` — Le dashboard interactif
- `data/` — Toutes les données (CSV, SHP, GeoTIFF, métadonnées)
- `requirements.txt` — Dépendances Python
- `.streamlit/config.toml` — Configuration du thème

## Comment lancer le dashboard en local

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py ou python -m streamlit run streamlit_app.py