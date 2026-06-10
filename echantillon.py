# ===============================================================
# COLLECTEUR DE TERRAIN - AVEC GPS AUTOMATIQUE
# ===============================================================
from pyproj import Transformer
import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import datetime
import math
import random
from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree

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
# CHEMINS (à adapter si nécessaire)
# ===============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "utils", "DATA", "OUTPUT", "grid_5m.csv")
IMAGES_DIR = os.path.join(os.path.dirname(CSV_PATH), "Images")
CHECKPOINT_FILE = os.path.join(os.path.dirname(CSV_PATH), "checkpoint_collecte.json")
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
    df = pd.read_csv(CSV_PATH)
    if "True_color" not in df.columns:
        df["True_color"] = ""
    if "True_color_20cm" not in df.columns:
        df["True_color_20cm"] = ""
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


def find_cell_with_distance(lat, lon, tree, polygons, df, tolerance_deg=0.00003):
    point = Point(lon, lat)
    candidates = tree.query(point)
    for idx in candidates:
        poly = polygons[idx]
        poly_buffer = poly.buffer(tolerance_deg)
        if poly_buffer.contains(point) or poly_buffer.touches(point):
            return df.iloc[idx]["NOM"], 0.0, True
    best_idx = None
    best_dist_m = float('inf')
    for idx, poly in enumerate(polygons):
        dist_deg = poly.distance(point)
        dist_m = dist_deg * 111000
        if dist_m < best_dist_m:
            best_dist_m = dist_m
            best_idx = idx
    if best_idx is not None:
        return df.iloc[best_idx]["NOM"], best_dist_m, False
    return None, None, False


# ===============================================================
# SAUVEGARDES
# ===============================================================
def save_image(uploaded_file, cell_name, suffix):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{cell_name}_{suffix}_{ts}.jpg"
    path = os.path.join(IMAGES_DIR, filename)
    with open(path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return os.path.relpath(path, os.path.dirname(CSV_PATH)).replace("\\", "/")


def update_csv(cell_name, true_color_path, true_color_20cm_path):
    df = pd.read_csv(CSV_PATH)
    mask = df["NOM"] == cell_name
    if mask.any():
        df.loc[mask, "True_color"] = true_color_path
        df.loc[mask, "True_color_20cm"] = true_color_20cm_path
        df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
        return True
    return False


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            return json.load(f)
    return {"sampled_cells": []}


def save_checkpoint(sampled_cells):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"sampled_cells": list(sampled_cells)}, f, indent=2)


def random_displacement(lat, lon, distance_m=30):
    r = distance_m + random.uniform(-5, 5)
    angle = random.uniform(0, 2 * math.pi)
    lat_rad = math.radians(lat)
    dy = r / 111320.0
    dx = r / (111320.0 * math.cos(lat_rad))
    return lat + dy * math.sin(angle), lon + dx * math.cos(angle)


def normalize_coordinates(a, b):
    if a > 1000 and b > 1000:
        lon, lat = utm_to_wgs84.transform(a, b)
        return lat, lon
    if abs(a) <= 180 and abs(b) <= 90:
        return b, a
    if abs(a) <= 90 and abs(b) <= 180:
        return a, b
    return None, None


# ===============================================================
# FONCTION GPS (composant HTML)
# ===============================================================
def get_gps_component():
    """
    Affiche un composant HTML qui demande la position GPS et la renvoie via une query param.
    Retourne None si pas encore appelé, sinon (lat, lon).
    """
    html_code = """
    <div id="gps-container">
        <button id="get-location" style="padding:10px; background-color:#4CAF50; color:white; border:none; border-radius:5px; cursor:pointer;">
            📍 Obtenir ma position GPS
        </button>
        <div id="status" style="margin-top:10px; font-size:14px; color:#333;"></div>
    </div>
    <script>
        const button = document.getElementById('get-location');
        const statusDiv = document.getElementById('status');
        
        button.addEventListener('click', () => {
            statusDiv.innerHTML = '🔄 Recherche du GPS...';
            if (!navigator.geolocation) {
                statusDiv.innerHTML = '❌ Votre navigateur ne supporte pas la géolocalisation.';
                return;
            }
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    const lat = position.coords.latitude;
                    const lon = position.coords.longitude;
                    statusDiv.innerHTML = `✅ Position : ${lat.toFixed(6)}, ${lon.toFixed(6)}`;
                    // Envoyer à Streamlit via un paramètre d'URL (technique simple)
                    const url = new URL(window.parent.location.href);
                    url.searchParams.set('gps_lat', lat);
                    url.searchParams.set('gps_lon', lon);
                    window.parent.location.href = url.href;
                },
                (error) => {
                    let msg = '';
                    switch(error.code) {
                        case error.PERMISSION_DENIED: msg = 'Permission refusée.'; break;
                        case error.POSITION_UNAVAILABLE: msg = 'Position indisponible.'; break;
                        case error.TIMEOUT: msg = 'Délai dépassé.'; break;
                        default: msg = 'Erreur inconnue.';
                    }
                    statusDiv.innerHTML = `❌ GPS : ${msg}`;
                },
                { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
            );
        });
    </script>
    """
    # On affiche le composant
    st.components.v1.html(html_code, height=120)
    
    # Lire les paramètres d'URL
    query_params = st.query_params
    if "gps_lat" in query_params and "gps_lon" in query_params:
        try:
            lat = float(query_params["gps_lat"])
            lon = float(query_params["gps_lon"])
            # Nettoyer les paramètres pour éviter une boucle
            st.query_params.clear()
            return lat, lon
        except:
            return None
    return None


# ===============================================================
# INTERFACE PRINCIPALE
# ===============================================================
def main():
    st.title("📸 Collecteur d'échantillons - GPS automatique")

    with st.spinner("Chargement de la grille..."):
        df, tree, polygons = load_grid()

    total = len(df)
    objectif = int(total * 0.05)
    cp = load_checkpoint()
    deja_fait = set(cp["sampled_cells"])
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
    # GPS AUTOMATIQUE
    # ===========================================================
    st.subheader("📍 Obtenir ma position GPS")
    gps_coords = get_gps_component()
    if gps_coords:
        lat, lon = gps_coords
        st.success(f"📍 Position GPS : {lat:.6f}, {lon:.6f}")
        st.session_state.gps_lat = lat
        st.session_state.gps_lon = lon
        # On supprime l'ancienne cellule pour forcer la recherche
        st.session_state.pop("current_cell", None)
        st.rerun()

    # ===========================================================
    # SAISIE MANUELLE (en cas de panne GPS)
    # ===========================================================
    with st.expander("📝 Saisie manuelle (si GPS indisponible)"):
        col1, col2 = st.columns(2)
        with col1:
            coord1 = st.number_input("Coordonnée 1", value=0.0, format="%.6f", key="man_coord1")
        with col2:
            coord2 = st.number_input("Coordonnée 2", value=0.0, format="%.6f", key="man_coord2")
        
        if st.button("🔍 Valider cette position manuelle"):
            lat, lon = normalize_coordinates(coord1, coord2)
            if lat is None or lon is None:
                st.error("Impossible de détecter le type de coordonnées")
            else:
                st.success(f"Position saisie : {lat:.6f}, {lon:.6f}")
                st.session_state.gps_lat = lat
                st.session_state.gps_lon = lon
                st.session_state.pop("current_cell", None)
                st.rerun()

    # ===========================================================
    # AFFICHAGE POSITION ACTUELLE ET RECHERCHE MAILLE
    # ===========================================================
    if "gps_lat" in st.session_state:
        lat, lon = st.session_state.gps_lat, st.session_state.gps_lon
        st.info(f"📍 Position actuelle : {lat:.6f}, {lon:.6f}")

        cell_name, distance, trouve = find_cell_with_distance(lat, lon, tree, polygons, df, tolerance_deg=0.00003)

        if not trouve:
            st.error(f"❌ Vous n'êtes dans aucune maille (distance à la plus proche : {distance:.1f} m)")
            if cell_name:
                st.info(f"📌 Maille la plus proche : **{cell_name}** à {distance:.1f} m")
                if st.button("✅ Utiliser quand même cette maille"):
                    st.session_state.current_cell = cell_name
                    st.rerun()
            if st.button("🚶 Générer un point aléatoire (~30m)"):
                new_lat, new_lon = random_displacement(lat, lon, 30)
                st.session_state.gps_lat = new_lat
                st.session_state.gps_lon = new_lon
                st.session_state.pop("current_cell", None)
                st.rerun()
        else:
            st.success(f"✅ Vous êtes dans la maille **{cell_name}** (distance {distance:.1f} m)")
            st.session_state.current_cell = cell_name

    # ===========================================================
    # PRISE DE PHOTOS
    # ===========================================================
    if "current_cell" in st.session_state:
        cell = st.session_state.current_cell
        if cell in deja_fait:
            st.warning(f"⚠️ La maille {cell} a déjà été échantillonnée. Déplacez-vous.")
            if st.button("🚶 Se déplacer aléatoirement (~30m)"):
                new_lat, new_lon = random_displacement(lat, lon, 30)
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
                    if update_csv(cell, p1, p2):
                        deja_fait.add(cell)
                        save_checkpoint(deja_fait)
                        st.success(f"✅ Maille {cell} enregistrée !")
                        st.session_state.pop("current_cell", None)
                        st.rerun()
                    else:
                        st.error("Erreur écriture CSV")

    # ===========================================================
    # DERNIERES MAILLES
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
            sorted_mailes = sorted(maille_imgs.keys(), reverse=True)
            for maille in sorted_mailes[:3]:
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

    if st.button("🛑 Sauvegarder et quitter"):
        st.success("Progression sauvegardée.")
        st.stop()


if __name__ == "__main__":
    main()