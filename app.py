import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import json
import re

st.set_page_config(page_title="Warehouse 2D Racking", page_icon="📦", layout="wide", initial_sidebar_state="expanded")

# ==========================================================
# FIREBASE INIT
# ==========================================================
if not firebase_admin._apps:
    cert_dict = json.loads(st.secrets["textkey"])
    cred = credentials.Certificate(cert_dict)
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================================
# LOAD DATA (SMART CACHE - MENCEGAH LIMIT QUOTA HABIS)
# ==========================================================
@st.cache_data(ttl=900) # Cache bertahan 15 menit
def load_data_from_firebase():
    docs = db.collection('uji_coba_rak').stream()
    data = [doc.to_dict() for doc in docs]
    df = pd.DataFrame(data)
    
    # Standarisasi kolom
    for c in df.columns:
        if c.strip().lower() in ['palet ke', 'pallet ke']:
            df.rename(columns={c: 'Pallet Ke'}, inplace=True)
            
    for col in ['Baris', 'Pallet Ke']:
        if col in df.columns: 
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    return df

st.sidebar.header("🔄 Sinkronisasi Database")
st.sidebar.info("Untuk menghemat kuota, data dikunci (cache) per 15 menit. Klik tombol di bawah jika butuh data paling Real-Time.")
if st.sidebar.button("🔄 Tarik Data Terbaru", use_container_width=True):
    st.cache_data.clear()
    st.success("Menarik data terbaru dari server...")
    st.rerun()

st.sidebar.divider()
st.sidebar.header("👁️ Mode Tampilan Grid")
mode_tampilan = st.sidebar.radio("Angka pada kotak rak menunjukkan:", ["Variasi SKU (Jenis Barang)", "Sisa Slot Kosong"])

st.title("📦 Visualisasi Grid Gudang")
st.caption("Mode Online Terhubung dengan Firebase Firestore")

df = load_data_from_firebase()
if df.empty or 'Kolom' not in df.columns:
    st.warning("Data masih kosong atau sedang memuat...")
    st.stop()

product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'

# ==========================================================
# LOGIKA GRID & MATRIKS (ANTI-ERROR)
# ==========================================================
st.sidebar.header("🔍 Pencarian & Filter")
daftar_barang = sorted(df[df[product_col].astype(str).str.strip() != ""][product_col].dropna().astype(str).unique().tolist()) if product_col in df.columns else []
pilihan_pencarian = st.sidebar.selectbox("Pilih / Ketik Nama Barang:", options=["-- Tampilkan Semua --"] + daftar_barang)
search_query = "" if pilihan_pencarian == "-- Tampilkan Semua --" else pilihan_pencarian

def is_rack_exist(kolom, baris):
    if kolom == 'F' and baris < 5: return False
    if kolom == 'G' and baris < 17: return False
    return True

kolom_list = ['G', 'F', 'E', 'D', 'C', 'B', 'A']
baris_list = list(range(1, 29))
matrix_info = {}
total_critical = total_kosong = 0

for k in kolom_list:
    for b in baris_list:
        if not is_rack_exist(k, b):
            matrix_info[(k, b)] = {'exist': False}
            continue
            
        sub = df[(df['Kolom'] == k) & (float(b) == pd.to_numeric(df['Baris'], errors='coerce'))]
        is_all_box = False
        if 'Part Number' in sub.columns:
            p_nums = sub['Part Number'].dropna().astype(str).str.strip().str.upper()
            if not p_nums[p_nums != ""].empty: is_all_box = p_nums[p_nums != ""].str.endswith(('D', 'G')).all()
        
        max_slot = (32 if b <= 16 else 46) if is_all_box else (31 if b <= 16 else 44)
        prods = sub[sub['Part Number'].astype(str).str.strip() != ""]['Part Number'].unique() if 'Part Number' in sub.columns else []
        sku = len([p for p in prods if str(p).strip().lower() not in ["", "nan"]])
        filled = sub['Part Number'].apply(lambda x: str(x).strip().lower() not in ["", "nan"] and pd.notna(x)).sum() if 'Part Number' in sub.columns else 0
        usable_space = max(0, max_slot - filled)
        
        is_match = False
        if search_term := search_query:
            m_prod = sub[product_col].astype(str).str.contains(search_term, case=False, na=False).any() if product_col in sub.columns else False
            m_part = sub['Part Number'].astype(str).str.contains(search_term, case=False, na=False).any() if 'Part Number' in sub.columns else False
            is_match = m_prod or m_part
        
        if sku >= 4: total_critical += 1
        elif sku == 0: total_kosong += 1
        matrix_info[(k, b)] = {'exist': True, 'sku_cnt': sku, 'filled': filled, 'usable_space': usable_space, 'max_slot': max_slot, 'df_sub': sub, 'is_match': is_match}

# ==========================================================
# MODAL POP-UP RINCIAN RAK
# ==========================================================
@st.dialog("📦 Rincian Detail Rak", width="large")
def show_rack_detail(k, b, info):
    st.subheader(f"📍 Lokasi Racking: {k} - Baris {b}")
    st.columns(3)[0].metric("Variasi SKU", f"{info['sku_cnt']} Jenis")
    st.columns(3)[1].metric("Slot Terpakai", f"{info['filled']} / {info['max_slot']}")
    st.columns(3)[2].metric("Space Kosong", f"{info['usable_space']} Slot")
    st.divider()
    
    if info['sku_cnt'] > 0:
        df_master = pd.DataFrame()
        for f in ["Master_Produk.csv", "Master Produk.csv"]:
            try: df_master = pd.read_csv(f, sep=";") if ";" in open(f).readline() else pd.read_csv(f, sep=","); break
            except: pass
        if not df_master.empty and 'Part Number' in df_master.columns:
            df_master['Part Number Clean'] = df_master['Part Number'].astype(str).str.strip().str.upper()

        df_terisi = info['df_sub'][~info['df_sub']['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan"])]
        rekap_data = []
        
        for part_num in df_terisi['Part Number'].astype(str).str.strip().unique():
            df_prod = df_terisi[df_terisi['Part Number'].astype(str).str.strip() == part_num]
            prod_name = str(df_prod[product_col].dropna().values[0]) if product_col in df_prod.columns and not df_prod[product_col].dropna().empty else "-"
            jml_utuh = df_prod[~df_prod['Keterangan'].astype(str).str.contains('Pecahan|Eceran', case=False, na=False)].shape[0]
            
            pecahan_rows = df_prod[df_prod['Keterangan'].astype(str).str.contains('Pecahan|Eceran', case=False, na=False)]
            v_pecahan = v_eceran = 0
            if not pecahan_rows.empty:
                k_str = str(pecahan_rows['Keterangan'].iloc[0]).lower()
                if mp := re.search(r'pecahan:\s*(\d+)', k_str): v_pecahan = int(mp.group(1))
                if me := re.search(r'eceran:\s*(\d+)', k_str): v_eceran = int(me.group(1))

            pnc, ip, pb, ps = str(part_num).strip().upper(), 0, 0, 0
            if not df_master.empty and pnc in df_master['Part Number Clean'].values:
                mr = df_master[df_master['Part Number Clean'] == pnc].iloc[0]
                ip, pb, ps = float(mr.get('Isi 1 Pallet (pcs)', 0) or 0), float(mr.get('Box / Pallet', 0) or 0), float(mr.get('Sac / Pallet', 0) or 0)

            sc = "Dus" if pnc.endswith('D') else "Sak"
            pss = pb if pnc.endswith('D') else ps
            
            teks = f"{jml_utuh} Pallet"
            if ip > 0:
                tot = (jml_utuh * ip) + (v_pecahan * pss) + v_eceran
                teks = f"{jml_utuh} Pllt * {ip:,.0f}" + (f" + {v_pecahan} {sc} * {pss:,.0f}" if v_pecahan>0 else "") + (f" + {v_eceran} Pcs" if v_eceran>0 else "") + f" = **Total {tot:,.0f} Pcs**"
            rekap_data.append({'Part Number': pnc, 'Nama Produk': prod_name, 'Pallet Utuh': jml_utuh, 'Konversi Total Pcs': teks})
        
        st.markdown("#### 📊 Rekapitulasi Stok")
        st.dataframe(pd.DataFrame(rekap_data), use_container_width=True, hide_index=True)
        st.markdown("#### 📑 Rincian per Pallet")
        avail = [c for c in ['Pallet Ke', 'Part Number', 'Lot Number', product_col, 'Keterangan', 'Grand Total Pcs'] if c in df_terisi.columns]
        st.dataframe(df_terisi[avail].sort_values(by='Pallet Ke') if 'Pallet Ke' in avail else df_terisi[avail], use_container_width=True, hide_index=True)
    else:
        st.success("✅ Baris ini KOSONG. Siap digunakan!")

# ==========================================================
# RENDER GRID (DENGAN ANGKA BARIS DI ATAS)
# ==========================================================
c1, c2, c3 = st.columns(3)
c1.metric("Total Baris Aktif", "156 Baris")
c2.metric("Baris Kritis (>=4 SKU)", f"{total_critical} Baris")
c3.metric("Baris Kosong", f"{total_kosong} Baris")
st.divider()

dynamic_css = """
.block-container { max-width: 98% !important; padding-top: 3.5rem !important; padding-bottom: 2rem !important; }
div[data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; }
div[data-testid="stColumn"] { padding-left: 2px !important; padding-right: 2px !important; }
div[data-testid="stColumn"]:nth-child(1) { display: flex; align-items: center; justify-content: center; }
div[class^="st-key-btn_"] button {
    aspect-ratio: 1/1 !important; width: 100% !important; min-width: 22px !important;
    padding: 0px !important; margin: 0px !important; border: 1px solid #475569 !important; border-radius: 4px !important; font-weight: 900 !important;
}
div[class^="st-key-btn_"] button:hover { transform: scale(1.15); border: 2px solid #fff !important; z-index: 10; }
"""
cmap = {'match': ["#38bdf8", "#000"], 'critical': ["#ef4444", "#fff"], 'warning': ["#fde047", "#000"], 'ideal': ["#86efac", "#000"], 'empty': ["#e2e8f0", "#94a3b8"]}
groups = {k: [] for k in cmap}

for k in kolom_list:
    for b in baris_list:
        info = matrix_info.get((k, b))
        if not info or not info['exist']: continue
        sku = info['sku_cnt']
        sel = f".st-key-btn_{k}_{b} button"
        if info['is_match']: groups['match'].append(sel)
        elif sku >= 4: groups['critical'].append(sel)
        elif sku == 3: groups['warning'].append(sel)
        elif sku in [1, 2]: groups['ideal'].append(sel)
        else: groups['empty'].append(sel)

for grp, sels in groups.items():
    if sels: dynamic_css += f"\n{', '.join(sels)} {{ background-color: {cmap[grp][0]} !important; color: {cmap[grp][1]} !important; }}"
st.markdown(f"<style>{dynamic_css}</style>", unsafe_allow_html=True)

def render_grid_area(title, start_baris, end_baris):
    st.markdown(f"### {title}")
    # Header Nomor Baris
    hc = st.columns([0.6] + [1] * 16, gap="small")
    hc[0].empty()
    for idx, b in enumerate(range(start_baris, end_baris + 1)):
        with hc[idx + 1]: st.markdown(f"<div style='text-align:center; font-weight:900; font-size:14px; color:#94a3b8; margin-bottom:4px;'>{b}</div>", unsafe_allow_html=True)
    
    for k in kolom_list:
        cols = st.columns([0.6] + [1] * 16, gap="small")
        with cols[0]: st.markdown(f"<div style='font-weight:900;'>{k}</div>", unsafe_allow_html=True)
        for idx, b in enumerate(range(start_baris, end_baris + 1)):
            info = matrix_info[(k, b)]
            with cols[idx + 1]:
                if info['exist']:
                    lbl = str(info['usable_space']) if mode_tampilan == "Sisa Slot Kosong" else str(info['sku_cnt'])
                    if st.button(lbl, key=f"btn_{k}_{b}", use_container_width=True): show_rack_detail(k, b, info)

render_grid_area("📍 Area 1 (Rak 1 - 16)", 1, 16)
st.divider()
render_grid_area("📍 Area 2 (Rak 17 - 28)", 17, 28)
