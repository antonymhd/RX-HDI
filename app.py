import re
import pandas as pd
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore

# ==========================================================
# 1. PAGE CONFIG
# ==========================================================
st.set_page_config(
    page_title="Warehouse 2D Racking",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==========================================================
# 2. FIREBASE INIT
# ==========================================================
NAMA_DATABASE = "uji_coba_rak"

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================================
# 3. HELPERS
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
    return series.astype(str).str.contains(keyword.strip(), case=False, na=False, regex=False).any()

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
# 4. LOAD FIREBASE (CACHED)
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
# 5. BUILD MATRIX SUMMARY (GROUPBY)
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
                matrix_info[(k, b)] = {"exist": is_rack_exist(k, b)} 
        return matrix_info, total_critical, total_kosong, kolom_list, baris_list

    gb = df.groupby(["Kolom", "Baris"], dropna=False)
    summary = {}
    for (k, b), sub in gb:
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

        is_all_box = False
        if not p_valid.empty:
            is_all_box = bool(p_valid.str.upper().str.endswith(("D", "G")).all())

        if is_all_box:
            max_slot = 32 if b <= 16 else 46
        else:
            max_slot = 31 if b <= 16 else 44

        usable_space = max(0, max_slot - filled)

        is_match = False
        if search_term:
            m_part = safe_contains(sub["Part Number"], search_term) if "Part Number" in sub.columns else False
            m_prod = safe_contains(sub[product_col], search_term) if product_col and (product_col in sub.columns) else False
            is_match = bool(m_part or m_prod)

        summary[(k, b)] = {
            "exist": True,
            "sku_cnt": sku_count,
            "filled": filled,
            "usable_space": usable_space,
            "max_slot": max_slot,
            "is_match": is_match,
            "sub": sub,  # keep sub for detail dialog (it's okay cached)
        }

        if sku_count >= 4:
            total_critical += 1
        elif sku_count == 0:
            total_kosong += 1

    for k in kolom_list:
        for b in baris_list:
            if not is_rack_exist(k, b):
                matrix_info[(k, b)] = {"exist": False}
            else:
                matrix_info[(k, b)] = summary.get((k, b), {
                    "exist": True,
                    "sku_cnt": 0,
                    "filled": 0,
                    "usable_space": 31 if b <= 16 else 44,
                    "max_slot": 31 if b <= 16 else 44,
                    "is_match": False,
                    "sub": df[(df["Kolom"] == k) & (df["Baris"] == b)].copy()
                })

    return matrix_info, total_critical, total_kosong, kolom_list, baris_list

# ==========================================================
# 6. DIALOG DETAIL
# ==========================================================
@st.dialog("📦 Rincian Detail Rak", width="large")
def show_rack_detail(k: str, b: int, info: dict):
    st.subheader(f"📍 Lokasi Racking: {k} - Baris {b}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Variasi SKU", f"{info['sku_cnt']} Jenis")
    c2.metric("Slot Fisik Terpakai", f"{info['filled']} / {info['max_slot']}")
    c3.metric("Space Kosong", f"{info['usable_space']} Slot")
    st.divider()

    df_sub = info.get("sub", pd.DataFrame())
    if df_sub.empty:
        st.success("✅ Rak Kosong. Aman untuk diisi.")
        return

    if info["sku_cnt"] > 0:
        df_master = load_master_produk()
        valid_part_mask = df_sub["Part Number"].astype(str).str.strip().map(is_valid_part_number) if "Part Number" in df_sub.columns else pd.Series([False]*len(df_sub))
        df_terisi = df_sub.loc[valid_part_mask].copy()

        rekap_data = []
        for part_num in df_terisi["Part Number"].astype(str).str.strip().unique():
            if not part_num:
                continue
            df_prod = df_terisi[df_terisi["Part Number"].astype(str).str.strip() == part_num].copy()

            prod_name = "-"
            if product_col in df_prod.columns and not df_prod.empty:
                valid_names = df_prod[product_col].dropna().astype(str).unique()
                if len(valid_names) > 0:
                    prod_name = str(valid_names[0])

            jml_utuh = 0
            val_pecahan = 0
            val_eceran = 0

            for _, row in df_prod.iterrows():
                ket_str = str(row.get("Keterangan", "")).lower()
                is_pecahan = "pecahan" in ket_str or "eceran" in ket_str
                if not is_pecahan:
                    jml_utuh += 1
                else:
                    mp = re.search(r"pecahan:\s*(\d+)", ket_str)
                    if mp:
                        val_pecahan += int(mp.group(1))
                    else:
                        nums = re.findall(r"\d+", ket_str)
                        if nums and "pecahan" in ket_str:
                            val_pecahan += int(nums[0])
                    me = re.search(r"eceran:\s*(\d+)", ket_str)
                    if me:
                        val_eceran += int(me.group(1))

            ip = pb = ps = 0
            pnc = part_num.strip().upper()
            if not df_master.empty and "Part Number Clean" in df_master.columns and pnc in df_master["Part Number Clean"].values:
                mr = df_master[df_master["Part Number Clean"] == pnc].iloc[0]
                ip = pd.to_numeric(mr.get("Isi 1 Pallet (pcs)", 0), errors="coerce")
                ip = 0 if pd.isna(ip) else float(ip)
                pb = pd.to_numeric(mr.get("Box / Pallet", 0), errors="coerce")
                pb = 0 if pd.isna(pb) else float(pb)
                ps = pd.to_numeric(mr.get("Sac / Pallet", 0), errors="coerce")
                ps = 0 if pd.isna(ps) else float(ps)

            sc = "Dus" if pnc.endswith("D") else "Sak"
            pss = pb if pnc.endswith("D") else ps

            if ip > 0:
                total_pcs = (jml_utuh * ip) + (val_pecahan * pss) + val_eceran
                teks_rincian = f"{jml_utuh} Pallet * {ip:,.0f}"
                if val_pecahan > 0:
                    teks_rincian += f" + {val_pecahan} {sc} * {pss:,.0f}"
                if val_eceran > 0:
                    teks_rincian += f" + {val_eceran} Pcs"
                teks_rincian += f" = **Total {total_pcs:,.0f} Pcs**"
            else:
                teks_rincian = f"{jml_utuh} Pallet"

            rekap_data.append({
                "Part Number": pnc,
                "Nama Produk": prod_name,
                "Pallet Utuh": jml_utuh,
                "Konversi Total Pcs": teks_rincian,
            })

        st.markdown("#### 📊 Rekapitulasi Stok (Otomatis)")
        st.dataframe(pd.DataFrame(rekap_data), use_container_width=True, hide_index=True)
        st.write("")
        st.markdown("#### 📑 Rincian Posisi per Pallet")
        avail = [c for c in ["Pallet Ke", "Part Number", "Lot Number", product_col, "Keterangan"] if c in df_terisi.columns]
        df_tampil = df_terisi[avail].copy()
        if "Pallet Ke" in df_tampil.columns:
            df_tampil = df_tampil.sort_values(by="Pallet Ke", ascending=True)
        st.dataframe(df_tampil, use_container_width=True, hide_index=True)
    else:
        st.success("✅ Rak Kosong. Aman untuk diisi.")

# ==========================================================
# 7. RENDER & CSS (RESPONSIVE + COLOR MAP)
# ==========================================================
def render_grid_area(title: str, start_baris: int, end_baris: int):
    st.markdown(f"### {title}")
    # Wrapper khusus supaya hanya grid yang horizontal-scrollable
    st.markdown("<div class='rack-grid-shell'>", unsafe_allow_html=True)

    header_cols = st.columns([0.6] + [1] * 16, gap="small")
    with header_cols[0]:
        st.empty()

    row_numbers = list(range(start_baris, end_baris + 1))
    for idx, b in enumerate(row_numbers):
        with header_cols[idx + 1]:
            st.markdown(
                f"<div style='text-align:center; font-weight:900; font-size:14px; color:#94a3b8; margin-bottom:4px;'>{b}</div>",
                unsafe_allow_html=True,
            )

    for k in kolom_list:
        cols = st.columns([0.6] + [1] * 16, gap="small")
        with cols[0]:
            st.markdown(f"<div style='font-weight:900; padding-top:6px;'>{k}</div>", unsafe_allow_html=True)
        for idx, b in enumerate(row_numbers):
            info = matrix_info.get((k, b), {"exist": False})
            with cols[idx + 1]:
                if info.get("exist", False):
                    lbl = str(info["usable_space"]) if mode_tampilan == "Sisa Slot Kosong" else str(info["sku_cnt"])
                    # key same pattern as CSS selectors below
                    if st.button(lbl, key=f"btn_{k}_{b}", use_container_width=True):
                        show_rack_detail(k, b, info)

    st.markdown("</div>", unsafe_allow_html=True)

# ==========================================================
# 8. MAIN
# ==========================================================
df = load_data_from_firebase()

st.sidebar.header("🔄 Sinkronisasi Real-Time")
st.sidebar.info("Data dikunci selama 5 menit untuk menghemat kuota Firebase. Klik tombol di bawah jika butuh update instan.")

if st.sidebar.button("🔄 Tarik Data Gudang Terbaru", use_container_width=True, type="primary"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()

st.sidebar.header("👁️ Mode Tampilan Kotak")
mode_tampilan = st.sidebar.radio(
    "Angka di dalam kotak rak mewakili:",
    ["Variasi SKU (Jenis Barang)", "Sisa Slot Kosong"],
)

st.sidebar.divider()
st.sidebar.header("🔍 Cari Barang")

if df.empty or "Kolom" not in df.columns:
    st.warning("Gudang kosong atau aplikasi sedang sinkronisasi. Harap tunggu...")
    st.stop()

product_col = get_product_column(df)
if product_col:
    valid_mask = df["Part Number"].astype(str).str.strip().map(is_valid_part_number) if "Part Number" in df.columns else pd.Series([False] * len(df))
    df_valid = df.loc[valid_mask].copy()
    daftar_barang = sorted(df_valid[product_col].dropna().astype(str).unique().tolist())
else:
    daftar_barang = []

pilihan_pencarian = st.sidebar.selectbox("Cari Posisi Barang:", options=["-- Tampilkan Semua --"] + daftar_barang)
search_query = "" if pilihan_pencarian == "-- Tampilkan Semua --" else pilihan_pencarian

matrix_info, total_critical, total_kosong, kolom_list, baris_list = build_matrix_summary(df, search_query, product_col)

# Header / metrics
st.title("📦 Visualisasi Grid Gudang (Live Monitor)")
st.caption(f"Layar pantau Read-Only. Terhubung ke database: {NAMA_DATABASE}")

col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("Total Baris Aktif", "156 Baris")
col_m2.metric("Rak Kritis (>= 4 SKU)", f"{total_critical} Baris")
col_m3.metric("Rak Kosong Bersih", f"{total_kosong} Baris")
st.divider()

# RESPONSIVE CSS + COLOR MAP (lebih robust selector set)
dynamic_css = """
.block-container { max-width: 98% !important; padding-top: 3.5rem !important; padding-bottom: 2rem !important; }
.rack-grid-shell { overflow-x: auto; -webkit-overflow-scrolling: touch; padding-bottom: 0.75rem; }
.rack-grid-shell > div { min-width: 980px; } /* memastikan grid tidak mengecil total */
div[data-testid="stColumn"] { padding-left: 2px !important; padding-right: 2px !important; }

div[class^="st-key-btn_"] button, button[data-baseweb*="button"] {
    aspect-ratio: 1/1 !important;
    width: 100% !important;
    min-width: 32px !important;
    max-width: 60px !important;
    padding: 0px !important;
    margin: 0px !important;
    border: 1px solid #475569 !important;
    border-radius: 6px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    font-weight: 900 !important;
    font-size: 13px !important;
}
div[class^="st-key-btn_"] button:hover { transform: scale(1.08); border: 2px solid #fff !important; z-index: 10; }

@media (max-width: 820px) {
  .rack-grid-shell > div { min-width: 820px; }
  div[class^="st-key-btn_"] button, button[data-baseweb*="button"] {
    min-width: 24px !important; max-width: 40px !important; font-size: 10px !important; border-radius: 5px !important;
  }
}
"""

# Build color_map and selectors (we make selectors flexible to match common Streamlit DOM patterns)
color_map = {
    "match": {"bg": "deepskyblue", "txt": "black", "sel": []},
    "critical": {"bg": "crimson", "txt": "white", "sel": []},
    "warning": {"bg": "gold", "txt": "black", "sel": []},
    "ideal": {"bg": "palegreen", "txt": "black", "sel": []},
    "empty": {"bg": "gainsboro", "txt": "gray", "sel": []},
}

# Create selectors for each cell. We'll add multiple patterns to increase chance of matching DOM.
for k in kolom_list:
    for b in baris_list:
        info = matrix_info.get((k, b))
        if not info or not info.get("exist", False):
            continue
        sku = info.get("sku_cnt", 0)
        # primary selector used earlier in original app
        sel1 = f".st-key-btn_btn_{k}_{b} button"   # fallback pattern (some builds prefix key)
        sel2 = f".st-key-btn_btn_{k}_{b} > button"
        sel3 = f".st-key-btn_{k}_{b} button"
        sel4 = f".st-key-btn_{k}_{b} > button"
        # button text cannot be selected via CSS, so we rely on generated class prefixes
        chosen = None
        if info.get("is_match", False):
            color_map["match"]["sel"].extend([sel1, sel2, sel3, sel4])
        elif sku >= 4:
            color_map["critical"]["sel"].extend([sel1, sel2, sel3, sel4])
        elif sku == 3:
            color_map["warning"]["sel"].extend([sel1, sel2, sel3, sel4])
        elif sku in [1, 2]:
            color_map["ideal"]["sel"].extend([sel1, sel2, sel3, sel4])
        else:
            color_map["empty"]["sel"].extend([sel1, sel2, sel3, sel4])

for group in color_map.values():
    unique_selectors = []
    for s in group["sel"]:
        if s not in unique_selectors:
            unique_selectors.append(s)
    if unique_selectors:
        # Build rule that tries several small selector patterns together
        dynamic_css += f"\n{', '.join(unique_selectors)} {{ background-color: {group['bg']} !important; color: {group['txt']} !important; }}"

st.markdown(f"<style>{dynamic_css}</style>", unsafe_allow_html=True)

# RENDER AREAS
render_grid_area("📍 Area 1 (Rak 1 - 16)", 1, 16)
st.divider()
render_grid_area("📍 Area 2 (Rak 17 - 28)", 17, 28)
