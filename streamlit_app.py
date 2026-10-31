# ============================================================
# DASHBOARD WEBGIS — SUIVI DES PLANTATIONS LOUGA–BANDEGNE
# Version finale : 4 indices, filtres actifs, légendes dynamiques
# Auteur : Awa Camara Diallo — Université Amadou Mahtar Mbow
# ============================================================

import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
import plotly.express as px
from pathlib import Path
import shapely.geometry
from pyproj import Transformer
import rasterio
from rasterio.warp import transform_bounds
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from PIL import Image
import base64
import io
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# CONFIGURATION
# ============================================================
st.set_page_config(page_title="WebGIS — Louga–Bandegne", page_icon="🌿", layout="wide")
DATA_DIR = Path("data")
RESULTATS_DIR = Path("resultats")

# ============================================================
# PALETTES DE COULEURS PAR INDICE
# ============================================================
PALETTES = {
    "NDVI": "RdYlGn",   # Rouge → Jaune → Vert (vigueur)
    "SAVI": "YlGn",     # Jaune → Vert (ajusté au sol)
    "EVI":  "plasma",   # Violet → Orange (amélioré)
    "NDMI": "BrBG",     # Marron → Bleu (humidité)
}

# ============================================================
# COULEURS PAR ÉTAT SANITAIRE
# ============================================================
COULEURS_ETAT = {
    "arbre en bonne sante": "green",
    "arbre peu stresse": "yellow",
    "arbre stresse": "orange",
    "arbre tres stresse": "darkred",
    "arbre mort": "red"
}

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
# FONCTION : Conversion GeoTIFF → tableau numpy + légende PNG
# ============================================================
@st.cache_data
def raster_to_array_with_legend(tif_path, band=1, cmap_name="RdYlGn", indice_name="NDVI", alpha=0.7):
    if not tif_path.exists():
        return None, None, None, None, None
    
    with rasterio.open(tif_path) as src:
        data = src.read(band).astype(float)
        nodata = src.nodata
        if nodata is not None:
            data[data == nodata] = np.nan
        bounds = src.bounds
        crs = src.crs
    
    vals = data[~np.isnan(data)]
    if len(vals) == 0: return None, None, None, None, None
    
    vmin = float(np.nanpercentile(vals, 2))
    vmax = float(np.nanpercentile(vals, 98))
    
    cmap = plt.get_cmap(cmap_name)
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
    rgba = cmap(norm(data))
    rgba = (rgba * 255).astype(np.uint8)
    rgba[..., 3] = np.where(np.isnan(data), 0, int(alpha * 255))
    
    img = Image.fromarray(rgba)
    
    bounds_wgs = transform_bounds(crs, 'EPSG:4326',
                                   bounds.left, bounds.bottom,
                                   bounds.right, bounds.top)
    extent = [[bounds_wgs[1], bounds_wgs[0]], [bounds_wgs[3], bounds_wgs[2]]]
    
    # Création de la légende
    fig, ax = plt.subplots(figsize=(4, 0.6))
    gradient = np.linspace(vmin, vmax, 256).reshape(1, -1)
    ax.imshow(gradient, aspect='auto', cmap=cmap_name, extent=[vmin, vmax, 0, 1])
    ax.set_yticks([])
    ax.set_xticks([vmin, (vmin + vmax) / 2, vmax])
    ax.set_xticklabels([f'{vmin:.2f}', f'{(vmin + vmax) / 2:.2f}', f'{vmax:.2f}'], fontsize=8)
    ax.set_xlabel(f'{indice_name}', fontsize=9, fontweight='bold')
    plt.tight_layout()
    
    buf_leg = io.BytesIO()
    fig.savefig(buf_leg, format='png', dpi=100, bbox_inches='tight')
    plt.close(fig)
    buf_leg.seek(0)
    legend_b64 = base64.b64encode(buf_leg.getvalue()).decode()
    
    return np.array(img), extent, vmin, vmax, legend_b64

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
# 2. CARTE INTERACTIVE AVEC 4 INDICES ET FILTRES
# ============================================================
st.header("🗺️ Carte interactive avec requêtes et 4 indices")

col_map1, col_map2 = st.columns([1, 3])

with col_map1:
    st.markdown("**1. Choisir le fond de carte**")
    fond = st.radio("Fond", ["Satellite", "Plan (OSM)"], label_visibility="collapsed")

    st.markdown("**2. Superposer les couches**")
    couches_choisies = st.multiselect(
        "Couches",
        ["Buffer 500m", "Reboisement", "Talus", "Points de plantation"],
        default=["Buffer 500m", "Reboisement", "Talus", "Points de plantation"]
    )

    st.markdown("**3. Afficher un indice (Raster)**")
    mois_raster = st.selectbox("Mois", ["Aucun", "Septembre", "Mars", "Variation"])
    if mois_raster in ["Septembre", "Mars", "Variation"]:
        indice_raster = st.selectbox("Indice", list(PALETTES.keys()))
        palette_choisie = PALETTES[indice_raster]
    else:
        indice_raster = None
        palette_choisie = None

    st.markdown("**4. Filtre attributaire (état sanitaire)**")
    if not df_points.empty and "Etat_arbre" in df_points.columns:
        etats_disponibles = df_points["Etat_arbre"].dropna().unique().tolist()
        etats_choisis = st.multiselect("États", etats_disponibles, default=etats_disponibles)
    else:
        etats_choisis = []

    st.markdown("**5. Filtre attributaire (NDVI)**")
    seuil_ndvi = st.slider("Seuil NDVI min (sept. 2026)", 0.0, 0.8, 0.2, 0.05)

    st.markdown("**6. Requête spatiale (buffer)**")
    utiliser_buffer = st.checkbox("Activer")
    if utiliser_buffer:
        point_x = st.number_input("Longitude", value=-16.38, format="%.6f")
        point_y = st.number_input("Latitude", value=15.58, format="%.6f")
        rayon_m = st.number_input("Rayon (m)", value=500, step=100)

with col_map2:
    # --- Filtres sur les points ---
    df_points_filtres = gdf_points.copy()
    
    # Filtre 1 : état sanitaire
    if etats_choisis and "Etat_arbre" in df_points_filtres.columns:
        df_points_filtres = df_points_filtres[df_points_filtres["Etat_arbre"].isin(etats_choisis)]
    
    # Filtre 2 : NDVI minimum
    if not df_points_filtres.empty and "NDVI" in df_points_filtres.columns:
        df_sept_filtres = df_points_filtres[df_points_filtres["Mois"] == "Septembre"] if "Mois" in df_points_filtres.columns else df_points_filtres
        df_points_filtres = df_sept_filtres[df_sept_filtres["NDVI"] >= seuil_ndvi]
    
    # Filtre 3 : requête spatiale (buffer)
    if utiliser_buffer and not df_points_filtres.empty:
        rayon_deg = rayon_m / 111000
        point_central = shapely.geometry.Point(point_x, point_y)
        buffer_zone = point_central.buffer(rayon_deg)
        df_points_filtres = df_points_filtres[df_points_filtres.geometry.within(buffer_zone)]

    # --- Création de la carte ---
    m = folium.Map(location=[15.58, -16.38], zoom_start=13, tiles=None)
    
    # Fond de carte
    if fond == "Satellite":
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri",
            name="Satellite Esri"
        ).add_to(m)
    else:
        folium.TileLayer("OpenStreetMap", name="OSM").add_to(m)

    # --- Vecteurs ---
    if "Buffer 500m" in couches_choisies and not shp_buffer.empty:
        folium.GeoJson(shp_buffer, name="Buffer 500m",
                       style_function=lambda x: {"color": "#d62728", "weight": 2, "fillOpacity": 0}).add_to(m)
    if "Reboisement" in couches_choisies and not shp_reboisement.empty:
        folium.GeoJson(shp_reboisement, name="Reboisement",
                       style_function=lambda x: {"color": "#e80909", "weight": 2, "fillOpacity": 0.3}).add_to(m)
    if "Talus" in couches_choisies and not shp_talus.empty:
        folium.GeoJson(shp_talus, name="Talus",
                       style_function=lambda x: {"color": "#9467bd", "weight": 2, "fillOpacity": 0.6}).add_to(m)
    
    # --- Points de plantation filtrés (AVEC couleurs selon état) ---
    if "Points de plantation" in couches_choisies and not df_points_filtres.empty:
        fg_points = folium.FeatureGroup(name="Plantations")
        for _, row in df_points_filtres.iterrows():
            etat = row.get("Etat_arbre", "")
            # Couleur selon l'état sanitaire
            couleur = COULEURS_ETAT.get(etat, "gray")
            
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=3,
                color=couleur,
                fill=True,
                fillColor=couleur,
                fillOpacity=0.8,
                popup=f"État (mai 2026) : {etat}"
            ).add_to(fg_points)
        fg_points.add_to(m)

    # --- Raster (conversion en tableau numpy + légende) ---
    legend_html = None
    if mois_raster != "Aucun" and indice_raster:
        if mois_raster == "Variation":
            tif_path = DATA_DIR / f"Variation_{indice_raster}_Mars_Septembre_2026.tif"
            band = 1
        else:
            tif_path = DATA_DIR / f"Indices_{mois_raster}_2026.tif"
            band = {"NDVI": 1, "SAVI": 2, "EVI": 3, "NDMI": 4}[indice_raster]

        if tif_path.exists():
            png_array, extent, vmin, vmax, legend_b64 = raster_to_array_with_legend(
                tif_path, band=band, cmap_name=palette_choisie, indice_name=indice_raster, alpha=0.7
            )
            if png_array is not None:
                folium.raster_layers.ImageOverlay(
                    image=png_array,
                    bounds=extent,
                    opacity=0.7,
                    name=f"{indice_raster} — {mois_raster}"
                ).add_to(m)
                st.success(f"✅ {indice_raster} de {mois_raster} affiché (palette : {palette_choisie})")
                
                # Légende dans la carte
                legend_html = f"""
                <div style="position: fixed; 
                            bottom: 50px; right: 50px; width: 250px; height: auto; 
                            background-color: white; border:2px solid grey; z-index:9999; 
                            font-size:12px; padding: 8px; border-radius: 5px;">
                    <b>{indice_raster} — {mois_raster}</b><br>
                    <img src="data:image/png;base64,{legend_b64}" style="width: 100%;"><br>
                    <small>Valeurs : {vmin:.2f} → {vmax:.2f}</small>
                </div>
                """
            else:
                st.error("Impossible de lire le raster")
        else:
            st.error(f"Fichier introuvable : {tif_path.name}")

    folium.LayerControl().add_to(m)
    
    if legend_html:
        m.get_root().html.add_child(folium.Element(legend_html))
    
    st_folium(m, width=1200, height=600, returned_objects=[])
    
    # --- Résumé des filtres appliqués ---
    st.caption(f"**{len(df_points_filtres)} points** affichés après application des filtres.")
    
    # --- Légende des états sanitaires (sous la carte) ---
    st.markdown("**Légende des états sanitaires (mai 2026) :**")
    cols_legende = st.columns(len(COULEURS_ETAT))
    for i, (etat, couleur) in enumerate(COULEURS_ETAT.items()):
        with cols_legende[i]:
            st.markdown(f"<span style='color:{couleur}; font-size:20px;'>●</span> {etat}", 
                        unsafe_allow_html=True)

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
