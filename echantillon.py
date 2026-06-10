# ===============================================================
# COLLECTEUR DE TERRAIN - GPS AVEC RECHERCHE IMMÉDIATE
# ===============================================================
from pyproj import Transformer
import streamlit as st
import pandas as pd
import numpy as np
import os
import datetime
import math
import random
from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree
from utils import utils_upload_b2
from streamlit_geolocation import streamlit_geolocation

# ===============================================================
# TRANSFORMATIONS COORDONNEES
# ===============================================================
utm_to_wgs84 = Transformer.from_crs("EPSG:32631", "EPSG:4326", always_xy=True)
wgs84_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32631", always_xy=True)

# ===============================================================
# CONFIG PAGE
# ===============================================================
st.set_page_config(page_title="Collecteur terrain - GPS auto", page_icon="📸", layout="wide")

# ===============================================================
# CHEMINS
# ===============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_GRID_PATH = os.path.join(BASE_DIR, "utils", "DATA", "OUTPUT", "grid_5m.csv")
CSV_RESULTS_PATH = os.path.join(BASE_DIR, "utils", "DATA", "OUTPUT", "resultats_grid_5m.csv")
IMAGES_DIR = os.path.join(os.path.dirname(CSV_GRID_PATH), "Images")
os.makedirs(IMAGES_DIR, exist_ok=True)

# ===============================================================
# FONCTIONS POLYGONES
# ===============================================================
def parse_ways_points(ways_points_str):
    coords = []
    for point in ways_points_str.split(';'):
        if ',' in point:
            x, y = point.split(',')
            x = float(x)
            y = float(y)
            if x > 1000 and y > 1000:
                lon, lat = utm_to_wgs84.transform(x, y)
            else:
                lon, lat = x, y
            coords.append((lon, lat))
    if len(coords) < 3:
        return None
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return Polygon(coords)

@st.cache_resource
def load_grid():
    df = pd.read_csv(CSV_GRID_PATH)
    polygons = []
    valid_idx = []
    for idx, row in df.iterrows():
        poly = parse_ways_points(row["ways_points"])
        if poly and poly.is_valid:
            polygons.append(poly)
            valid_idx.append(idx)
    df_valid = df.loc[valid_idx].reset_index(drop=True)
    tree = STRtree(polygons)
    return df_valid, tree, polygons

def load_results():
    if os.path.exists(CSV_RESULTS_PATH):
        df_results = pd.read_csv(CSV_RESULTS_PATH)
        if "True_color" not in df_results.columns:
            df_results["True_color"] = ""
        if "True_color_20cm" not in df_results.columns:
            df_results["True_color_20cm"] = ""
    else:
        df_grid = pd.read_csv(CSV_GRID_PATH)
        df_results = df_grid.copy()
        df_results["True_color"] = ""
        df_results["True_color_20cm"] = ""
        df_results.to_csv(CSV_RESULTS_PATH, index=False, encoding="utf-8-sig")
    return df_results

def save_results(df_results):
    df_results.to_csv(CSV_RESULTS_PATH, index=False, encoding="utf-8-sig")

def get_sampled_cells(df_results):
    mask = (df_results["True_color"].notna() & df_results["True_color"].astype(str).str.strip().ne("")) & \
           (df_results["True_color_20cm"].notna() & df_results["True_color_20cm"].astype(str).str.strip().ne(""))
    return set(df_results.loc[mask, "NOM"])

def update_results(cell_name, true_color_path, true_color_20cm_path):
    df = load_results()
    mask = df["NOM"] == cell_name
    if mask.any():
        df.loc[mask, "True_color"] = true_color_path
        df.loc[mask, "True_color_20cm"] = true_color_20cm_path
        save_results(df)
        return True
    return False

def find_cell_with_distance(lat, lon, tree, polygons, df_grid, tolerance_deg=0.00003):
    point = Point(lon, lat)
    candidates = tree.query(point)
    for idx in candidates:
        poly = polygons[idx]
        poly_buffer = poly.buffer(tolerance_deg)
        if poly_buffer.contains(point) or poly_buffer.touches(point):
            return df_grid.iloc[idx]["NOM"], 0.0, True
    best_idx = None
    best_dist_m = float('inf')
    for idx, poly in enumerate(polygons):
        dist_deg = poly.distance(point)
        dist_m = dist_deg * 111000
        if dist_m < best_dist_m:
            best_dist_m = dist_m
            best_idx = idx
    if best_idx is not None:
        return df_grid.iloc[best_idx]["NOM"], best_dist_m, False
    return None, None, False

def save_image(uploaded_file, cell_name, suffix):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{cell_name}_{suffix}_{ts}.jpg"
    path = os.path.join(IMAGES_DIR, filename)
    with open(path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return os.path.relpath(path, os.path.dirname(CSV_GRID_PATH)).replace("\\", "/")

def random_displacement(lat, lon, distance_m=30):
    r = distance_m + random.uniform(-5, 5)
    angle = random.uniform(0, 2 * math.pi)
    lat_rad = math.radians(lat)
    dy = r / 111320.0
    dx = r / (111320.0 * math.cos(lat_rad))
    return lat + dy * math.sin(angle), lon + dx * math.cos(angle)

def main():
    st.title("📸 Collecteur d'échantillons - GPS automatique")

    with st.spinner("Chargement de la grille..."):
        df_grid, tree, polygons = load_grid()
        df_results = load_results()
        deja_fait = get_sampled_cells(df_results)

    total = len(df_grid)
    objectif = int(total * 0.05)
    nb_fait = len(deja_fait)

    st.subheader("📊 État de la collecte")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📦 Total mailles", total)
    col2.metric("🎯 Objectif (5%)", objectif)
    col3.metric("✅ Déjà traitées", nb_fait)
    col4.metric("⏳ Restantes", max(0, objectif - nb_fait))
    if objectif:
        st.progress(min(nb_fait/objectif, 1.0), text=f"{nb_fait} / {objectif}")

    if nb_fait >= objectif:
        st.success("🎉 Objectif 5% atteint !")
        st.balloons()
        return

    # ===========================================================
    # GPS : récupération et recherche immédiate (streamlit-geolocation)
    # ===========================================================
    st.subheader("📍 Obtenir ma position GPS")

    location = streamlit_geolocation()

    if location is not None:
        # Récupération robuste selon le type retourné
        if isinstance(location, dict):
            lat = location.get("latitude")
            lon = location.get("longitude")
        elif hasattr(location, 'latitude'):  # objet avec attributs
            lat = location.latitude
            lon = location.longitude
        else:
            lat = lon = None
            st.warning("Format de géolocalisation non reconnu")

        if lat is not None and lon is not None:
            st.success(f"Position GPS détectée : {lat:.6f}, {lon:.6f}")
            st.session_state.gps_lat = lat
            st.session_state.gps_lon = lon

            # Recherche de la maille
            cell_name, distance, trouve = find_cell_with_distance(lat, lon, tree, polygons, df_grid)
            if trouve:
                st.session_state.current_cell = cell_name
                st.success(f"✅ Vous êtes dans la maille **{cell_name}**")
                st.rerun()
            else:
                st.error(f"❌ Aucune maille trouvée (plus proche : {cell_name} à {distance:.1f} m)")
                st.info("Vous pouvez utiliser la saisie manuelle ci-dessous.")
        else:
            st.info("Cliquez sur le bouton 'Get Location' pour autoriser la géolocalisation.")
    else:
        st.info("Cliquez sur le bouton 'Get Location' qui apparaît pour autoriser la géolocalisation.")

    # ===========================================================
    # Saisie manuelle (en secours)
    # ===========================================================
    with st.expander("📝 Saisie manuelle des coordonnées"):
        col1, col2 = st.columns(2)
        with col1:
            lat_man = st.number_input("Latitude", value=st.session_state.get("gps_lat", 0.0), format="%.6f")
        with col2:
            lon_man = st.number_input("Longitude", value=st.session_state.get("gps_lon", 0.0), format="%.6f")
        if st.button("🔍 Valider cette position"):
            st.session_state.gps_lat = lat_man
            st.session_state.gps_lon = lon_man
            st.session_state.pop("current_cell", None)
            st.rerun()

    # ===========================================================
    # Si une position est en session, on affiche la maille trouvée (si elle existe)
    # ===========================================================
    if "gps_lat" in st.session_state and "current_cell" not in st.session_state:
        lat, lon = st.session_state.gps_lat, st.session_state.gps_lon
        st.info(f"📍 Position actuelle : {lat:.6f}, {lon:.6f}")
        cell_name, distance, trouve = find_cell_with_distance(lat, lon, tree, polygons, df_grid)
        if not trouve:
            st.error(f"❌ Pas de maille à cette position (distance min: {distance:.1f} m)")
            if cell_name:
                if st.button(f"✅ Utiliser la maille la plus proche : {cell_name}"):
                    st.session_state.current_cell = cell_name
                    st.rerun()
            if st.button("🚶 Se déplacer aléatoirement (~30m)"):
                new_lat, new_lon = random_displacement(lat, lon, 30)
                st.session_state.gps_lat = new_lat
                st.session_state.gps_lon = new_lon
                st.session_state.pop("current_cell", None)
                st.rerun()
        else:
            st.success(f"✅ Vous êtes dans la maille **{cell_name}**")
            st.session_state.current_cell = cell_name
            st.rerun()

    # ===========================================================
    # Prise de photos
    # ===========================================================
    if "current_cell" in st.session_state:
        cell = st.session_state.current_cell
        if cell in deja_fait:
            st.warning(f"⚠️ La maille {cell} a déjà été échantillonnée. Déplacez-vous.")
            if st.button("🚶 Générer un point aléatoire (~30m)"):
                new_lat, new_lon = random_displacement(st.session_state.gps_lat, st.session_state.gps_lon, 30)
                st.session_state.gps_lat = new_lat
                st.session_state.gps_lon = new_lon
                st.session_state.pop("current_cell", None)
                st.rerun()
        else:
            st.subheader(f"📸 Échantillonnage de la maille **{cell}**")
            st.markdown("### 📷 **Première photo - Surface**")
            photo1 = st.camera_input("📷 Photo 1 (surface)")
            if photo1 is not None:
                st.image(photo1, caption="Aperçu surface", width=300)

            st.markdown("### 📷 **Deuxième photo - Profondeur 20 cm**")
            photo2 = st.camera_input("📷 Photo 2 (profondeur 20 cm)")
            if photo2 is not None:
                st.image(photo2, caption="Aperçu profondeur", width=300)

            if st.button("💾 Enregistrer les deux photos"):
                if photo1 is None or photo2 is None:
                    st.error("Veuillez prendre les deux photos")
                else:
                    p1 = save_image(photo1, cell, "surface")
                    p2 = save_image(photo2, cell, "depth20cm")
                    if update_results(cell, p1, p2):
                        deja_fait.add(cell)
                        st.success(f"✅ Maille {cell} enregistrée !")
                        st.session_state.pop("current_cell", None)
                        st.rerun()
                    else:
                        st.error("Erreur écriture des résultats")

    # ===========================================================
    # Dernières mailles échantillonnées
    # ===========================================================
    with st.expander("📷 Dernières mailles échantillonnées"):
        if os.path.exists(IMAGES_DIR):
            images = [f for f in os.listdir(IMAGES_DIR) if f.endswith(".jpg")]
            maille_imgs = {}
            for img in images:
                parts = img.split('_')
                if len(parts) >= 2:
                    maille = parts[0]
                    maille_imgs.setdefault(maille, []).append(img)
            for maille in list(maille_imgs.keys())[:3]:
                st.markdown(f"**Maille {maille}**")
                colA, colB = st.columns(2)
                surf = next((img for img in maille_imgs[maille] if "surface" in img), None)
                prof = next((img for img in maille_imgs[maille] if "depth20cm" in img), None)
                with colA:
                    if surf:
                        st.image(os.path.join(IMAGES_DIR, surf), caption="Surface", width=150)
                with colB:
                    if prof:
                        st.image(os.path.join(IMAGES_DIR, prof), caption="Profondeur", width=150)
                st.markdown("---")

    # ===========================================================
    # Sauvegarde et upload
    # ===========================================================
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🛑 Sauvegarder et quitter"):
            st.success("Progression sauvegardée.")
            st.stop()
    with col2:
        if st.button("📤 Envoyer les données au cloud (B2)"):
            with st.spinner("Envoi en cours..."):
                success = utils_upload_b2.backup_and_upload(CSV_RESULTS_PATH, IMAGES_DIR)
                if success:
                    st.balloons()
                else:
                    st.error("Échec de l'upload.")

if __name__ == "__main__":
    main()