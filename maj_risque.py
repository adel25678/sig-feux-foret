import os
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

# ---------- Réglages ----------
BASE = "https://public-api.meteofrance.fr/public/DPPaquetObs/v2"
SORTIE = "risque_test.csv"
GARDER_INCOMPLETES = False
MIN_STATIONS = 100   # sécurité : en dessous, on n'écrase pas le fichier

SEUIL_TEMP, SEUIL_HUM, SEUIL_VENT = 30, 30, 30
NIVEAUX = {0: "Faible", 1: "Modéré", 2: "Élevé", 3: "Très élevé"}

# ---------- Authentification (jamais écrite dans le code) ----------
API_KEY = os.environ.get("MF_API_KEY")
TOKEN = os.environ.get("MF_TOKEN")
if API_KEY:
    headers = {"accept": "*/*", "apikey": API_KEY}
elif TOKEN:
    headers = {"accept": "*/*", "Authorization": f"Bearer {TOKEN}"}
else:
    raise SystemExit("Aucune clé trouvée : définis la variable MF_API_KEY.")

def calcul_risque(temp, hum, vent):
    if pd.isna(temp) or pd.isna(hum) or pd.isna(vent):
        return None, "Données incomplètes"
    nb = int(temp > SEUIL_TEMP) + int(hum < SEUIL_HUM) + int(vent > SEUIL_VENT)
    return nb, NIVEAUX[nb]

# ---------- 1. Télécharger toutes les stations ----------
maintenant = datetime.now(timezone.utc)
data = None
for recul in (15, 21, 27, 33):
    d = maintenant - timedelta(minutes=recul)
    d = d.replace(minute=(d.minute // 6) * 6, second=0, microsecond=0)
    date = d.strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get(f"{BASE}/paquet/stations/infrahoraire-6m",
                     headers=headers, params={"date": date, "format": "json"},
                     timeout=60)
    print(f"Date {date} -> code {r.status_code}")
    if r.status_code == 200 and r.json():
        data = r.json()
        break
if data is None:
    raise SystemExit("Aucune donnée récupérée (clé, abonnement ou date).")

lignes = [x["properties"] if "properties" in x else x for x in data]
obs = pd.DataFrame(lignes)
obs["id_station"] = obs["geo_id_insee"].astype(str).str.zfill(8)

# ---------- 2. Métropole + conversions ----------
stations = pd.read_csv("stations.csv", dtype={"id_station": str})
df = stations.merge(obs[["id_station", "t", "u", "ff", "validity_time"]],
                    on="id_station", how="inner")
df["temp"] = (df["t"] - 273.15).round(1)
df["humidite"] = df["u"]
df["vent"] = (df["ff"] * 3.6).round(1)
df["date_obs"] = df["validity_time"]

# ---------- 3. Règle 30-30-30 ----------
res = df.apply(lambda r: pd.Series(calcul_risque(r["temp"], r["humidite"], r["vent"])), axis=1)
df["nb_criteres"] = res[0].astype("Int64")
df["niveau_risque"] = res[1]
df["date_maj"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

if not GARDER_INCOMPLETES:
    df = df[df["niveau_risque"] != "Données incomplètes"]

# ---------- 4. Sécurité puis écriture ----------
if len(df) < MIN_STATIONS:
    raise SystemExit(f"Seulement {len(df)} stations : fichier NON écrasé.")

def fmt(v, modele):
    return "n/d" if pd.isna(v) else modele.format(v)

df["temp_txt"] = df["temp"].map(lambda v: fmt(v, "{:.1f} °C"))
df["humidite_txt"] = df["humidite"].map(lambda v: fmt(v, "{:.0f} %"))
df["vent_txt"] = df["vent"].map(lambda v: fmt(v, "{:.1f} km/h"))
df["heure_obs"] = (pd.to_datetime(df["date_obs"], utc=True)
                   .dt.tz_convert("Europe/Paris")
                   .dt.strftime("%d/%m/%Y %H:%M"))

colonnes = ["id_station", "nom", "lat", "lon", "temp", "humidite", "vent",
            "temp_txt", "humidite_txt", "vent_txt", "heure_obs",
            "date_obs", "nb_criteres", "niveau_risque", "date_maj"]
df[colonnes].to_csv(SORTIE, index=False, encoding="utf-8")

print(f"\n{len(df)} stations écrites dans {SORTIE}")
print(df["niveau_risque"].value_counts())
