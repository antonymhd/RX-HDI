import re
import pandas as pd
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore

# ==========================================================
# 1. KONFIGURASI HALAMAN
# ==========================================================
st.set_page_config(
    page_title="Warehouse 2D Racking",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==========================================================
# 2. INIT FIREBASE
# ==========================================================
NAMA_DATABASE = "uji_coba_rak"

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================================
# 3. FUNGSI BANTU
# ==========================================================
def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    rename_map = {}
    for col in list(df.columns):
        if col is None:
            continue
        key = str(col).strip().lower()
        if key in ("palet ke", "pallet ke"):
            rename_map[col] = "Pallet Ke"

    if rename_map:
        df = df.rename(columns=rename_map)

    if "Kolom" in df.columns:
        df["Kolom"] = df["Kolom"].astype(str).str.strip().str.upper()

    if "Baris" in df.columns:
        df["Baris"] = pd.to_numeric(df["Baris"], errors="coerce").fillna(0).astype(int)

    if "Pallet Ke" in df.columns:
        df["Pallet Ke"] = pd.to_numeric(df["Pallet Ke"], errors="coerce").fillna(0).astype(int)

    if "Part Number" in df.columns:
        df["Part Number"] = df["Part Number"].astype(str).str.strip()

    return df


def is_valid_part_number(value) -> bool:
    if pd.isna(value):
        return False
    text = str(value).strip()
    if text == "":
        return False
    if text.lower() in {"nan", "none", "<na>"}:
        return False
    return True


def get_product_column(df: pd.DataFrame) -> str:
    for col in ["Nama Produk", "Nama Barang"]:
        if col in df.columns:
            return col
    return ""


def is_rack_exist(kolom: str, baris: int) -> bool:
    if kolom == "F" and baris < 5:
        return False
    if kolom == "G" and baris < 17:
        return False
    return True


def safe_contains(series, keyword: str) -> bool:
    if not keyword or keyword.strip() == "":
        return False
    keyword = keyword.strip()
    return series.astype(str).str.contains(keyword, case=False, na=False, regex=False).any()


def load_master_produk():
    try:
        try:
            df_master = pd.read_csv("Master_Produk.csv", sep=";")
        except Exception:
            df_master = pd.read_csv("Master_Produk.csv", sep=",")
        if "Part Number" in df_master.columns:
            df_master["Part Number Clean"] = df_master["Part Number"].astype(str).str.strip().str.upper()
        return df_master
    except Exception:
        return pd.DataFrame()


# ==========================================================
# 4. LOAD DATA DARI FIREBASE
# ==========================================================
@st.cache_data(ttl=300)
def load_data_from_firebase():
    docs = db.collection(NAMA_DATABASE).stream()
    semua_data = []

    for doc in docs:
        doc_data = doc.to_dict()
        if isinstance(doc_data, dict) and "data" in doc_data and isinstance(doc_data["data"], list):
            semua_data.extend(doc_data["data"])

    if not semua_data:
        return pd.DataFrame()

    df = pd.DataFrame(semua_data)
    df = normalize_column_names(df)

    return df


# ==========================================================
# 5. BUILD MATRIX SUMMARY
# ==========================================================
def build_matrix_summary(df: pd.DataFrame, search_term: str, product_col: str):
    kolom_list = ["G", "F", "E", "D", "C", "B", "A"]
    baris_list = list(range(1, 29))

    matrix_info = {}
    total_critical = 0
    total_kosong = 0

    if df.empty or "Kolom" not in df.columns or "Baris" not in df.columns:
        for k in kolom_list:
            for b in baris_list:
                if is_rack_exist(k, b):
                    matrix_info[(k, b)] = {
                        "exist": True,
                        "sku_cnt": 0,
                        "filled": 0,
                        "usable_space": 0,
                        "max_slot": 0,
                        "is_match": False,
                    }
                else:
                    matrix_info[(k, b)] = {"exist": False}
        return matrix_info, total_critical, total_kosong, kolom_list, baris_list

    summary = {}

    for (k, b), sub in df.groupby(["Kolom", "Baris"], dropna=False):
        k = str(k).strip().upper()
        try:
            b = int(b)
        except Exception:
            continue

        if not is_rack_exist(k, b):
            continue

        sub = sub.copy()

        if "Part Number" in sub.columns:
            part_series = sub["Part Number"].astype(str).str.strip()
            valid_mask = part_series.map(is_valid_part_number)
            p_valid = part_series[valid_mask]
            filled = int(valid_mask.sum())
            sku_count = int(len(p_valid.unique()))
        else:
            filled = 0
            sku_count = 0
            p_valid = pd.Series(dtype=str)

        is_all_box = bool((not p_valid.empty) and p_valid.str.upper().str.endswith(("D", "G")).all())

        if is_all_box:
            max_slot = 32 if b <= 16 else 46
        else:
            max_slot = 31 if b <= 16 else 44

        usable_space = max(0, max_slot - filled)

        is_match = False
        if search_term:
            m_part = safe_contains(sub["Part Number"], search_term) if "Part Number" in sub.columns else False
            m_prod = safe_contains(sub[product_col], search_term) if product_col and product_col in sub.columns else False
            is_match = bool(m_part or m_prod)

        summary[(k, b)] = {
            "exist": True,
            "sku_cnt": sku_count,
            "filled": filled,
            "usable_space": usable_space,
            "max_slot":

