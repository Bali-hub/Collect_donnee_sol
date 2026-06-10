# utils_upload_b2.py
import os
import zipfile
import tempfile
import hashlib
import requests
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st

# Charger .env à la racine
ROOT_DIR = Path(__file__).resolve().parent
ENV_FILE = ROOT_DIR / ".env"
load_dotenv(ENV_FILE)

KEY_ID = os.getenv("B2_KEY_ID")
APP_KEY = os.getenv("B2_APPLICATION_KEY")
BUCKET_NAME = "ground-water-finder"  # à modifier si besoin

def auth():
    """Authentification B2"""
    r = requests.get(
        "https://api.backblazeb2.com/b2api/v2/b2_authorize_account",
        auth=(KEY_ID, APP_KEY),
        timeout=30
    )
    if not r.ok:
        raise Exception("❌ Authentification B2 échouée")
    return r.json()

def get_bucket(auth_data):
    """Récupère les infos du bucket"""
    r = requests.post(
        auth_data["apiUrl"] + "/b2api/v2/b2_list_buckets",
        headers={"Authorization": auth_data["authorizationToken"]},
        json={"accountId": auth_data["accountId"]},
        timeout=30
    )
    for b in r.json().get("buckets", []):
        if b["bucketName"] == BUCKET_NAME:
            return b
    raise Exception(f"❌ Bucket '{BUCKET_NAME}' introuvable")

def upload_file(file_path, auth_data, bucket):
    """Upload un fichier ZIP vers B2"""
    # Obtenir l'URL d'upload
    r = requests.post(
        auth_data["apiUrl"] + "/b2api/v2/b2_get_upload_url",
        headers={"Authorization": auth_data["authorizationToken"]},
        json={"bucketId": bucket["bucketId"]},
        timeout=30
    )
    if not r.ok:
        st.error("Erreur lors de la demande d'URL d'upload")
        return False

    up = r.json()
    upload_url = up["uploadUrl"]
    upload_auth = up["authorizationToken"]

    # Calcul du SHA1
    sha1 = hashlib.sha1()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha1.update(chunk)

    # Upload du fichier
    with open(file_path, "rb") as f:
        r = requests.post(
            upload_url,
            headers={
                "Authorization": upload_auth,
                "X-Bz-File-Name": file_path.name,
                "Content-Type": "application/zip",
                "X-Bz-Content-Sha1": sha1.hexdigest()
            },
            data=f,
            timeout=(30, 600)
        )
    return r.status_code == 200

def zip_folder(folder_path, output_zip_path):
    """Zippe tout le contenu d'un dossier"""
    with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, start=os.path.dirname(folder_path))
                zipf.write(file_path, arcname)

def backup_and_upload(results_csv_path, images_dir):
    """
    Zippe le CSV et le dossier Images, puis uploade les deux archives vers B2.
    Retourne True si tout est réussi.
    """
    if not KEY_ID or not APP_KEY:
        st.error("❌ Clés B2 manquantes. Vérifiez le fichier .env")
        return False

    try:
        auth_data = auth()
        bucket = get_bucket(auth_data)
    except Exception as e:
        st.error(f"Erreur d'authentification B2 : {e}")
        return False

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"collecte_{timestamp}"

    # Zipper le CSV
    csv_zip_path = tempfile.NamedTemporaryFile(delete=False, suffix=".zip").name
    with zipfile.ZipFile(csv_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(results_csv_path, arcname=os.path.basename(results_csv_path))

    # Zipper le dossier Images
    images_zip_path = tempfile.NamedTemporaryFile(delete=False, suffix=".zip").name
    zip_folder(images_dir, images_zip_path)

    # Upload des deux fichiers
    csv_ok = upload_file(Path(csv_zip_path), auth_data, bucket)
    images_ok = upload_file(Path(images_zip_path), auth_data, bucket)

    # Nettoyage des fichiers temporaires
    os.unlink(csv_zip_path)
    os.unlink(images_zip_path)

    if csv_ok and images_ok:
        st.success("✅ Données sauvegardées sur Backblaze B2 !")
        return True
    else:
        st.error("❌ Échec lors de l'upload.")
        return False