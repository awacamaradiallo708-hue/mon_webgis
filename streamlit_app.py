import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
import plotly.express as px
from pathlib import Path
import shapely.geometry
from pyproj import Transformer
import rasterio
from rasterio.warp import transform_bounds
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import io
from PIL import Image
import base64
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# CONFIGURATION
# ============================================================
st.set_page_config(page_title="WebGIS — Louga–Bandegne", page_icon="🌿", layout="wide")
DATA_DIR = Path("data")
RESULTATS_DIR = Path("resultats")

# ============================================================
# FONCTIONS DE CHARGEMENT
# ============================================================
@st.cache_data
def charger_csv(nom):
    chemin = DATA_DIR / nom
    return pd.read_csv(chemin) if chemin.exists() else pd.DataFrame()

@st.cache_data
def charger_shp(nom):
    chemin = DATA_DIR / nom
    if not chemin.exists(): return gpd.GeoDataFrame()
    gdf = gpd.read_file(chemin)
    return gdf.to_crs("EPSG:4326") if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf

@st.cache_data
def convertir_points(df, col_x="X", col_y="Y"):
    if df.empty or col_x not in df.columns: return gpd.GeoDataFrame()
    transformer = Transformer.from_crs("EPSG:32628", "EPSG:4326", always_xy=True)
    df_clean = df.dropna(subset=[col_x, col_y]).copy()
    df_clean["geometry"] = df_clean.apply(
        lambda r: shapely.geometry.Point(transformer.transform(r[col_x], r[col_y])[0],
                                          transformer.transform(r[col_x], r[col_y])[1]), axis=1)
    return gpd.GeoDataFrame(df_clean, geometry="geometry", crs="EPSG:4326")

# ============================================================
# FONCTION : CONVERSION DU GEOTIFF EN PNG POUR AFFICHAGE
# ============================================================
@st.cache_data
def raster_to_png_base64(tif_path, band=1, cmap_name="RdYlGn", vmin=None, vmax=None, alpha=0.7):
    """
    Convertit une bande d'un GeoTIFF en image PNG (base64) et retourne aussi l'extent WGS84.
    - band : numéro de la bande à lire (1=NDVI, 2=SAVI, 3=EVI, 4=NDMI)
    - cmap_name : palette de couleurs
    - vmin/vmax : bornes (si None, calcul sur percentiles 2/98)
    """
    if not tif_path.exists():
        return None, None
    
    with rasterio.open(tif_path) as src:
        data = src.read(band).astype(float)
        nodata = src.nodata
        if nodata is not None:
            data[data == nodata] = np.nan
        bounds = src.bounds
        crs = src.crs
    
    vals = data[~np.isnan(data)]
    if len(vals) == 0: return None, None
    
    if vmin is None: vmin = float(np.nanpercentile(vals, 2))
    if vmax is None: vmax = float(np.nanpercentile(vals, 98))
    
    cmap = plt.get_cmap(cmap_name)
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
    rgba = cmap(norm(data))
    rgba = (rgba * 255).astype(np.uint8)
    rgba[..., 3] = np.where(np.isnan(data), 0, int(alpha * 255))
    
    img = Image.fromarray(rgba)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    
    # Conversion de l'extent en WGS84
    bounds_wgs = transform_bounds(crs, 'EPSG:4326',
                                   bounds.left, bounds.bottom,
                                   bounds.right, bounds.top)
    extent = [[bounds_wgs[1], bounds_wgs[0]], [bounds_wgs[3], bounds_wgs[2]]]
    
    return buf.getvalue(), extent

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
st.info("ℹ️ **Note** : L'état sanitaire a été relevé en **mai 2026** ; les indices spectraux sont extraits de **septembre 2026**.")

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
# 2. CARTE INTERACTIVE AVEC TOUS LES INDICES ET REQUÊTES
# ============================================================
st.header("🗺️ Carte interactive avec requêtes et indices")

col_map1, col_map2 = st.columns([1, 3])

with col_map1:
    # --- Fond de carte ---
    st.markdown("**1. Choisir le fond de carte**")
    fond = st.radio("Fond", ["Satellite", "Plan (OSM)"], label_visibility="collapsed")

    # --- Couches vecteurs ---
    st.markdown("**2. Superposer les couches**")
    couches_choisies = st.multiselect(
        "Couches",
        ["Buffer 500m", "Reboisement", "Talus", "Points de plantation"],
        default=["Buffer 500m", "Reboisement", "Talus", "Points de plantation"]
    )

    # --- Choix du mois et de l'indice ---
    st.markdown("**3. Afficher un indice (Raster)**")
    mois_raster = st.selectbox("Mois", ["Septembre", "Mars", "Variation"])
    
    if mois_raster in ["Septembre", "Mars"]:
        indice_raster = st.selectbox("Indice", ["NDVI", "SAVI", "EVI", "NDMI"])
    else:
        indice_raster = st.selectbox("Indice", ["NDVI", "SAVI", "EVI", "NDMI"])

    # --- REQUÊTE ATTRIBUTAIRE : État sanitaire ---
    st.markdown("**4. Filtre attributaire (état sanitaire)**")
    if not df_points.empty and "Etat_arbre" in df_points.columns:
        etats_disponibles = df_points["Etat_arbre"].dropna().unique().tolist()
        etats_choisis = st.multiselect("États à afficher", etats_disponibles, default=etats_disponibles)
    else:
        etats_choisis = []

    # --- REQUÊTE ATTRIBUTAIRE : NDVI ---
    st.markdown("**5. Filtre attributaire (NDVI)**")
    seuil_ndvi = st.slider("Seuil NDVI minimum (sept. 2026)", 0.0, 0.8, 0.2, 0.05)

    # --- REQUÊTE SPATIALE ---
    st.markdown("**6. Requête spatiale (buffer)**")
    utiliser_buffer_requete = st.checkbox("Activer")
    if utiliser_buffer_requete:
        point_x = st.number_input("Longitude", value=-16.38, format="%.6f")
        point_y = st.number_input("Latitude", value=15.58, format="%.6f")
        rayon_m = st.number_input("Rayon (m)", value=500, step=100)

with col_map2:
    # --- Application des filtres sur les points ---
    df_points_filtres = gdf_points.copy()
    
    if etats_choisis and "Etat_arbre" in df_points_filtres.columns:
        df_points_filtres = df_points_filtres[df_points_filtres["Etat_arbre"].isin(etats_choisis)]
    
    if not df_points_filtres.empty and "NDVI" in df_points_filtres.columns:
        df_sept_filtres = df_points_filtres[df_points_filtres["Mois"] == "Septembre"] if "Mois" in df_points_filtres.columns else df_points_filtres
        df_points_filtres = df_sept_filtres[df_sept_filtres["NDVI"] >= seuil_ndvi]
    
    if utiliser_buffer_requete and not df_points_filtres.empty:
        rayon_deg = rayon_m / 111000
        point_central = shapely.geometry.Point(point_x, point_y)
        buffer_zone = point_central.buffer(rayon_deg)
        df_points_filtres = df_points_filtres[df_points_filtres.geometry.within(buffer_zone)]

    # --- Création de la carte Folium ---
    m = folium.Map(location=[15.58, -16.38], zoom_start=13, tiles=None)
    
    # Fond de carte
    if fond == "Satellite":
        folium.TileLayer(tiles="Esri WorldImagery", name="Satellite").add_to(m)
    else:
        folium.TileLayer(tiles="OpenStreetMap", name="OSM").add_to(m)

    # --- Ajout des vecteurs ---
    if "Buffer 500m" in couches_choisies and not shp_buffer.empty:
        folium.GeoJson(shp_buffer, name="Buffer 500m",
                       style_function=lambda x: {"color": "#d62728", "weight": 2, "fillOpacity": 0}).add_to(m)
    if "Reboisement" in couches_choisies and not shp_reboisement.empty:
        folium.GeoJson(shp_reboisement, name="Reboisement",
                       style_function=lambda x: {"color": "#e80909", "weight": 2, "fillOpacity": 0.3}).add_to(m)
    if "Talus" in couches_choisies and not shp_talus.empty:
        folium.GeoJson(shp_talus, name="Talus",
                       style_function=lambda x: {"color": "#9467bd", "weight": 2, "fillOpacity": 0.6}).add_to(m)
    if "Points de plantation" in couches_choisies and not df_points_filtres.empty:
        fg_points = folium.FeatureGroup(name="Plantations")
        for _, row in df_points_filtres.iterrows():
            etat = row.get("Etat_arbre", "")
            couleur = {"arbre en bonne sante": "green", "arbre mort": "red",
                       "arbre stresse": "orange", "arbre tres stresse": "darkred",
                       "arbre peu stresse": "yellow"}.get(etat, "gray")
            folium.CircleMarker(location=[row.geometry.y, row.geometry.x],
                                radius=3, color=couleur, fill=True, fillColor=couleur, fillOpacity=0.8,
                                popup=f"État : {etat}").add_to(fg_points)
        fg_points.add_to(m)

    # --- Ajout du raster (conversion PNG) ---
    if mois_raster == "Variation":
        tif_path = DATA_DIR / f"Variation_{indice_raster}_Mars_Septembre_2026.tif"
        band = 1
    else:
        tif_path = DATA_DIR / f"Indices_{mois_raster}_2026.tif"
        # Correspondance bande → indice
        band = {"NDVI": 1, "SAVI": 2, "EVI": 3, "NDMI": 4}[indice_raster]

    if tif_path.exists():
        png_data, extent = raster_to_png_base64(tif_path, band=band, cmap_name="RdYlGn", alpha=0.7)
        if png_data is not None:
            folium.raster_layers.ImageOverlay(
                image=png_data,
                bounds=extent,
                opacity=0.7,
                name=f"{indice_raster} — {mois_raster}"
            ).add_to(m)
            st.success(f"✅ {indice_raster} de {mois_raster} affiché")
        else:
            st.error("Impossible de lire le raster")
    else:
        st.error(f"Fichier introuvable : {tif_path.name}")

    folium.LayerControl().add_to(m)
    
    # Affichage de la carte dans Streamlit
    from streamlit_folium import st_folium
    st_folium(m, width=1200, height=600, returned_objects=[])
    
    st.caption(f"**{len(df_points_filtres)} points** correspondent aux filtres.")

st.divider()

# ============================================================
# 3. CATALOGUE ET TÉLÉCHARGEMENTS
# ============================================================
st.header("🗂️ Catalogue et téléchargement des données")
tab1, tab2, tab3 = st.tabs(["📄 CSV", "🗺️ GeoJSON", "🖼️ GeoTIFF"])

with tab1:
    if not df_points.empty:
        st.download_button("⬇️ Points (CSV)", df_points.to_csv(index=False).encode('utf-8'), "points.csv", "text/csv")
    if not df_matrice.empty:
        st.download_button("⬇️ Matrice (CSV)", df_matrice.to_csv(index=False).encode('utf-8'), "matrice.csv", "text/csv")

with tab2:
    if not shp_buffer.empty:
        st.download_button("⬇️ Buffer (GeoJSON)", shp_buffer.to_json(), "buffer.geojson", "application/json")
    if not shp_talus.empty:
        st.download_button("⬇️ Talus (GeoJSON)", shp_talus.to_json(), "talus.geojson", "application/json")
    if not shp_reboisement.empty:
        st.download_button("⬇️ Reboisement (GeoJSON)", shp_reboisement.to_json(), "reboisement.geojson", "application/json")

with tab3:
    for tif in sorted(DATA_DIR.glob("*.tif")):
        with open(tif, "rb") as f:
            st.download_button(f"⬇️ {tif.name}", f.read(), tif.name, "image/tiff", key=f"dl_{tif.name}")

st.divider()

# ============================================================
# 4. GRAPHIQUES ET FIGURES
# ============================================================
st.header("📈 Résultats et Analyses")
col_g1, col_g2 = st.columns(2)
with col_g1:
    if not df_sept.empty and "NDVI" in df_sept.columns:
        fig = px.box(df_sept, x="Etat_arbre", y="NDVI", color="Etat_arbre",
                     title="NDVI (sept. 2026) vs État sanitaire (mai 2026)")
        st.plotly_chart(fig, use_container_width=True)
with col_g2:
    png_files = sorted(RESULTATS_DIR.glob("*.png")) if RESULTATS_DIR.exists() else []
    if png_files:
        figure_choisie = st.selectbox("Choisir une figure", [p.name for p in png_files])
        st.image(str(RESULTATS_DIR / figure_choisie), caption=figure_choisie, width="stretch")

st.caption("© Awa Camara Diallo — Master 2 UAM — Octobre 2026")
