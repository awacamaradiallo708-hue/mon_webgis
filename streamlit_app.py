# ============================================================
# DASHBOARD WEBGIS — SUIVI DES PLANTATIONS LOUGA–BANDEGNE
# Version finale corrigée : rasters, requêtes, téléchargements
# Auteur : Awa Camara Diallo — Université Amadou Mahtar Mbow
# ============================================================
# PRÉREQUIS (à installer dans le terminal avant de lancer) :
#   pip install streamlit leafmap geopandas plotly xarray rioxarray localtileserver
# ============================================================

import os
os.environ['LOCALTILESERVER_CLIENT_PREFIX'] = 'proxy/{port}'
import streamlit as st
import pandas as pd
import geopandas as gpd
import leafmap.foliumap as leafmap
import plotly.express as px
from pathlib import Path
import shapely.geometry
from pyproj import Transformer
import warnings
warnings.filterwarnings('ignore')

# --- CONFIGURATION DES CHEMINS ---
# DATA_DIR : dossier contenant les CSV, SHP, TIF
# RESULTATS_DIR : dossier contenant les figures PNG du mémoire
st.set_page_config(page_title="WebGIS — Louga–Bandegne", page_icon="🌿", layout="wide")
DATA_DIR = Path("data")
RESULTATS_DIR = Path("resultats")

# ============================================================
# FONCTIONS DE CHARGEMENT (avec cache pour performance)
# ============================================================
@st.cache_data
def charger_csv(nom):
    """Charge un CSV du dossier data/."""
    chemin = DATA_DIR / nom
    return pd.read_csv(chemin) if chemin.exists() else pd.DataFrame()

@st.cache_data
def charger_shp(nom):
    """Charge un shapefile et le reprojette en WGS84 pour l'affichage web."""
    chemin = DATA_DIR / nom
    if not chemin.exists(): return gpd.GeoDataFrame()
    gdf = gpd.read_file(chemin)
    # Conversion en WGS84 (EPSG:4326) si le CRS est différent
    return gdf.to_crs("EPSG:4326") if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf

@st.cache_data
def convertir_points(df, col_x="X", col_y="Y"):
    """
    Convertit des points UTM 28N (EPSG:32628) en WGS84 (EPSG:4326).
    Nécessaire car les CSV GEE utilisent les coordonnées UTM en mètres,
    alors que Leaflet/Folium attend des degrés (latitude/longitude).
    """
    if df.empty or col_x not in df.columns: return gpd.GeoDataFrame()
    transformer = Transformer.from_crs("EPSG:32628", "EPSG:4326", always_xy=True)
    df_clean = df.dropna(subset=[col_x, col_y]).copy()
    df_clean["geometry"] = df_clean.apply(
        lambda r: shapely.geometry.Point(
            transformer.transform(r[col_x], r[col_y])[0],
            transformer.transform(r[col_x], r[col_y])[1]
        ), axis=1
    )
    return gpd.GeoDataFrame(df_clean, geometry="geometry", crs="EPSG:4326")

# ============================================================
# CHARGEMENT DES DONNÉES
# ============================================================
df_points = charger_csv("Indices_points_plantation_mensuels_2026.csv")
df_matrice = charger_csv("Matrice_Transition.csv")
shp_buffer = charger_shp("Autoroute_a_peage_Buffer_500m.shp")
shp_reboisement = charger_shp("limite_champ_reboisement_compensatoir.shp")
shp_talus = charger_shp("surface_talus_Regrouper.shp")
gdf_points = convertir_points(df_points)

# ============================================================
# 1. EN-TÊTE ET KPI
# ============================================================
st.title("🌿 WebGIS de suivi des plantations — Louga–Bandegne")
st.markdown("**Prototype fonctionnel** — Autoroute Dakar–Saint-Louis — Données : Mars à Septembre 2026")

# Avertissement sur le décalage temporel (état sanitaire mai vs indices septembre)
st.info(
    "ℹ️ **Note importante** : Les données d'état sanitaire ont été échantillonnées "
    "**au mois de mai 2026**, tandis que les indices spectraux sont extraits de "
    "**septembre 2026**. Ce décalage temporel de 4 mois doit être pris en compte."
)

st.header("📊 Indicateurs clés (KPI)")

# Calcul des KPI à partir des données
df_sept = df_points[df_points["Mois"] == "Septembre"] if "Mois" in df_points.columns else df_points
nb_total = len(df_sept)
nb_bonne_sante = (df_sept["Etat_arbre"] == "arbre en bonne sante").sum() if "Etat_arbre" in df_sept else 0
taux_survie = (nb_bonne_sante / nb_total * 100) if nb_total > 0 else 0
nb_alertes = (df_sept["NDVI"] < 0.2).sum() if "NDVI" in df_sept else 0
surface_ha = shp_reboisement.to_crs("EPSG:32628").geometry.area.sum() / 10000 if not shp_reboisement.empty else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Taux de survie (mai 2026)", f"{taux_survie:.1f} %", f"{nb_bonne_sante} / {nb_total} pts")
c2.metric("Surface reboisée", f"{surface_ha:.0f} ha", "Reboisement")
c3.metric("Talus suivis", f"{len(shp_talus)}", "Unités")
c4.metric("Alertes (NDVI < 0.2)", f"{nb_alertes}", "Septembre 2026", delta_color="inverse")

st.divider()

# ============================================================
# 2. CARTE INTERACTIVE AVEC REQUÊTES
# ============================================================
st.header("🗺️ Carte interactive avec requêtes")

# Deux colonnes : à gauche les filtres, à droite la carte
col_map1, col_map2 = st.columns([1, 3])

with col_map1:
    # --- Choix du fond de carte ---
    st.markdown("**1. Choisir le fond de carte**")
    fond = st.radio("Fond", ["Satellite", "Plan (OSM)"], label_visibility="collapsed")

    # --- Choix des couches à superposer ---
    st.markdown("**2. Superposer les couches**")
    couches_choisies = st.multiselect(
        "Couches",
        ["Buffer 500m", "Reboisement", "Talus", "Points de plantation"],
        default=["Buffer 500m", "Reboisement", "Talus", "Points de plantation"]
    )

    # --- Choix du raster à afficher ---
    st.markdown("**3. Afficher un indice (Raster)**")
    type_raster = st.selectbox(
        "Indice",
        ["Aucun", "NDVI Septembre", "NDVI Mars", "Variation NDVI (Mars-Sept)"]
    )

    # --- REQUÊTE ATTRIBUTAIRE : filtre par état sanitaire ---
    st.markdown("**4. Filtre attributaire (état sanitaire)**")
    if not df_points.empty and "Etat_arbre" in df_points.columns:
        etats_disponibles = df_points["Etat_arbre"].dropna().unique().tolist()
        etats_choisis = st.multiselect(
            "États à afficher",
            etats_disponibles,
            default=etats_disponibles
        )
    else:
        etats_choisis = []

    # --- REQUÊTE ATTRIBUTAIRE : filtre par NDVI ---
    st.markdown("**5. Filtre attributaire (NDVI)**")
    seuil_ndvi = st.slider("Seuil NDVI minimum (sept. 2026)", 0.0, 0.8, 0.2, 0.05)

    # --- REQUÊTE SPATIALE : buffer autour d'un point ---
    st.markdown("**6. Requête spatiale (buffer autour d'un point)**")
    utiliser_buffer_requete = st.checkbox("Activer la requête spatiale")
    if utiliser_buffer_requete:
        point_x = st.number_input("Longitude du point central", value=-16.38, format="%.6f")
        point_y = st.number_input("Latitude du point central", value=15.58, format="%.6f")
        rayon_m = st.number_input("Rayon (en mètres)", value=500, step=100)

with col_map2:
    # --- Application des filtres (requêtes) sur les points ---
    df_points_filtres = gdf_points.copy()

    # Filtre 1 : état sanitaire
    if etats_choisis and "Etat_arbre" in df_points_filtres.columns:
        df_points_filtres = df_points_filtres[df_points_filtres["Etat_arbre"].isin(etats_choisis)]

    # Filtre 2 : NDVI minimum (septembre)
    if not df_points_filtres.empty and "NDVI" in df_points_filtres.columns:
        df_sept_filtres = df_points_filtres[df_points_filtres["Mois"] == "Septembre"] if "Mois" in df_points_filtres.columns else df_points_filtres
        df_points_filtres = df_sept_filtres[df_sept_filtres["NDVI"] >= seuil_ndvi]

    # Filtre 3 : requête spatiale (buffer autour d'un point)
    if utiliser_buffer_requete and not df_points_filtres.empty:
        # Approximation : 1° de latitude ≈ 111 km
        rayon_deg = rayon_m / 111000
        point_central = shapely.geometry.Point(point_x, point_y)
        buffer_zone = point_central.buffer(rayon_deg)
        df_points_filtres = df_points_filtres[df_points_filtres.geometry.within(buffer_zone)]

    # --- Initialisation de la carte ---
    try:
        m = leafmap.Map(center=[15.58, -16.38], zoom=13, height=600)
    except Exception as e:
        st.error(f"Erreur d'initialisation de la carte : {e}")
        m = None

    if m is not None:
        # --- Fond de carte avec fallback ---
        if fond == "Satellite":
            try:
                m.add_basemap("Esri.WorldImagery")
            except Exception:
                try:
                    m.add_basemap("OpenTopoMap")
                except Exception:
                    m.add_basemap("OpenStreetMap")
        else:
            m.add_basemap("OpenStreetMap")

        # --- Ajout des couches vectorielles ---
        if "Buffer 500m" in couches_choisies and not shp_buffer.empty:
            m.add_gdf(shp_buffer, layer_name="Buffer 500m",
                      style={"color": "#d62728", "fillOpacity": 0})
        if "Reboisement" in couches_choisies and not shp_reboisement.empty:
            m.add_gdf(shp_reboisement, layer_name="Reboisement",
                      style={"color": "#e80909", "fillOpacity": 0.3})
        if "Talus" in couches_choisies and not shp_talus.empty:
            m.add_gdf(shp_talus, layer_name="Talus",
                      style={"color": "#9467bd", "fillOpacity": 0.6})
        if "Points de plantation" in couches_choisies and not df_points_filtres.empty:
            m.add_points_from_xy(df_points_filtres, x="X", y="Y", layer_name="Plantations filtrées")

        # --- Ajout du raster (nécessite localtileserver + xarray) ---
        if type_raster != "Aucun":
            if "NDVI Septembre" in type_raster:
                tif_path = DATA_DIR / "Indices_Septembre_2026.tif"
            elif "NDVI Mars" in type_raster:
                tif_path = DATA_DIR / "Indices_Mars_2026.tif"
            else:
                tif_path = DATA_DIR / "Variation_NDVI_Mars_Septembre_2026.tif"

            if tif_path.exists():
                try:
                    m.add_raster(str(tif_path), band=1, palette="RdYlGn",
                                 layer_name=type_raster, opacity=0.7)
                    st.success(f"✅ Raster {type_raster} affiché")
                except Exception as e:
                    st.error(f"❌ Erreur raster : {e}")
                    st.info("Installez localtileserver : pip install localtileserver")
            else:
                st.error(f"Fichier introuvable : {tif_path.name}")

        # --- Affichage de la carte ---
        m.to_streamlit(height=600)

    # --- Résumé des requêtes ---
    st.caption(f"**{len(df_points_filtres)} points** correspondent aux filtres appliqués.")

st.divider()

# ============================================================
# 3. CATALOGUE ET TÉLÉCHARGEMENTS
# ============================================================
st.header("🗂️ Catalogue et téléchargement des données")

# Trois onglets pour séparer les formats
tab1, tab2, tab3 = st.tabs(["📄 Fichiers CSV", "🗺️ Couches Vectorielles (GeoJSON)", "🖼️ Images Satellites (GeoTIFF)"])

with tab1:
    st.subheader("Données tabulaires")
    if not df_points.empty:
        st.download_button("⬇️ Points de plantation (CSV)",
                           df_points.to_csv(index=False).encode('utf-8'),
                           "points_plantation.csv", "text/csv")
    if not df_matrice.empty:
        st.download_button("⬇️ Matrice de transition (CSV)",
                           df_matrice.to_csv(index=False).encode('utf-8'),
                           "matrice_transition.csv", "text/csv")

with tab2:
    st.subheader("Couches vectorielles")
    if not shp_buffer.empty:
        st.download_button("⬇️ Buffer 500m (GeoJSON)",
                           shp_buffer.to_json(), "buffer_500m.geojson", "application/json")
    if not shp_reboisement.empty:
        st.download_button("⬇️ Reboisement (GeoJSON)",
                           shp_reboisement.to_json(), "reboisement.geojson", "application/json")
    if not shp_talus.empty:
        st.download_button("⬇️ Talus (GeoJSON)",
                           shp_talus.to_json(), "talus.geojson", "application/json")

with tab3:
    st.subheader("Images raster (Indices et Classifications)")
    tif_files = sorted(DATA_DIR.glob("*.tif"))
    if tif_files:
        for tif in tif_files:
            c1, c2 = st.columns([3, 1])
            with c1:
                st.write(f"**{tif.name}**")
            with c2:
                with open(tif, "rb") as f:
                    st.download_button("Télécharger", f.read(), tif.name, "image/tiff", key=f"dl_{tif.name}")
    else:
        st.info("Aucun fichier .tif trouvé.")

st.divider()

# ============================================================
# 4. GRAPHIQUES ET FIGURES DU MÉMOIRE
# ============================================================
st.header("📈 Résultats et Analyses")

col_g1, col_g2 = st.columns(2)

with col_g1:
    st.subheader("NDVI selon l'état sanitaire")
    if not df_sept.empty and "NDVI" in df_sept.columns:
        fig_box = px.box(df_sept, x="Etat_arbre", y="NDVI", color="Etat_arbre",
                         title="Distribution du NDVI (Sept 2026)")
        st.plotly_chart(fig_box, use_container_width=True)

with col_g2:
    st.subheader("Figures du mémoire")
    png_files = sorted(RESULTATS_DIR.glob("*.png")) if RESULTATS_DIR.exists() else []
    if png_files:
        # Sélecteur pour choisir la figure à afficher
        figure_choisie = st.selectbox("Choisir une figure à afficher", [p.name for p in png_files])
        chemin_figure = RESULTATS_DIR / figure_choisie
        if chemin_figure.exists():
            # CORRECTION : width="stretch" au lieu de use_column_width=True
            st.image(str(chemin_figure), caption=figure_choisie, width="stretch")
    else:
        st.info(f"Aucune figure PNG trouvée dans {RESULTATS_DIR}. Vérifiez le chemin.")

st.caption("© Awa Camara Diallo — Master 2 UAM — Octobre 2026 | Plateforme de suivi environnemental")
