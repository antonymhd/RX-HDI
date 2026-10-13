import streamlit as st
import pandas as pd
import re

st.set_page_config(
    page_title="Warehouse 2D Racking (OFFLINE)",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================================
# SIDEBAR
# ==========================================================
st.sidebar.header("🔄 Mode Offline")
st.sidebar.warning("Aplikasi sedang berjalan tanpa internet ke Firebase untuk melindungi kuota. Menampilkan data backup semalam.")
st.sidebar.divider()

st.sidebar.header("👁️ Mode Tampilan Grid")
mode_tampilan = st.sidebar.radio(
    "Angka pada kotak rak menunjukkan:",
    ["Variasi SKU (Jenis Barang)", "Sisa Slot Kosong"]
)

# TOMBOL CLEAR CACHE MANUAL DI SIDEBAR
st.sidebar.divider()
if st.sidebar.button("🧹 Bersihkan Cache (Jika Error File)"):
    st.cache_data.clear()
    st.success("Cache berhasil dibersihkan! Silakan refresh layar.")
    st.rerun()

# ==========================================================
# LOAD DATA DARI CSV LOKAL
# ==========================================================
st.title("📦 Visualisasi Grid Gudang (MODE DARURAT)")
st.caption("Menampilkan data berdasarkan backup CSV terbaru. Inbound/Outbound hari ini harap dicatat manual.")

@st.cache_data
def load_data_from_csv():
    try:
        nama_file_csv = "Audit_Stok_WMS_20261012.csv"
        
        # Coba baca dengan pemisah titik koma, jika gagal pakai koma
        try: df = pd.read_csv(nama_file_csv, sep=";")
        except: df = pd.read_csv(nama_file_csv, sep=",")
        
        # STANDARISASI NAMA KOLOM (Menyelesaikan masalah 'Palet ke' vs 'Pallet Ke')
        if 'Palet ke' in df.columns:
            df.rename(columns={'Palet ke': 'Pallet Ke'}, inplace=True)
            
        if 'Pallet ke' in df.columns:
            df.rename(columns={'Pallet ke': 'Pallet Ke'}, inplace=True)
        
        # Pastikan kolom tipe angka
        for col in ['Baris', 'Pallet Ke']:
            if col in df.columns: 
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        
        if 'Kolom' not in df.columns: return pd.DataFrame()
        return df
    except Exception as e:
        st.error(f"🚨 Gagal memuat CSV: {e}. Pastikan nama file adalah 'Audit_Stok_WMS_20261012.csv' di GitHub.")
        return None

df = load_data_from_csv()
if df is None or df.empty: st.stop()

product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'

# ==========================================================
# PENCARIAN & FILTER
# ==========================================================
st.sidebar.header("🔍 Pencarian & Filter")
if product_col in df.columns:
    daftar_barang = sorted(df[df[product_col].astype(str).str.strip() != ""][product_col].dropna().astype(str).unique().tolist())
else:
    daftar_barang = []
pilihan_pencarian = st.sidebar.selectbox("Pilih / Ketik Nama Barang:", options=["-- Tampilkan Semua --"] + daftar_barang)
search_query = "" if pilihan_pencarian == "-- Tampilkan Semua --" else pilihan_pencarian

# ==========================================================
# LOGIKA MATRIKS
# ==========================================================
def is_rack_exist(kolom, baris):
    if kolom == 'F' and baris < 5: return False
    if kolom == 'G' and baris < 17: return False
    return True

def process_matrix_data(df, search_term, prod_col):
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
                p_nums = p_nums[p_nums != ""]
                if not p_nums.empty: is_all_box = p_nums.str.endswith(('D', 'G')).all()
            
            max_slot = (32 if b <= 16 else 46) if is_all_box else (31 if b <= 16 else 44)
            prods = sub[sub['Part Number'].astype(str).str.strip() != ""]['Part Number'].unique() if 'Part Number' in sub.columns else []
            sku = len(prods)
            filled = sub['Part Number'].apply(lambda x: str(x).strip() != "" and pd.notna(x)).sum() if 'Part Number' in sub.columns else 0
            usable_space = max(0, max_slot - filled)
            
            is_match = False
            if search_term and prod_col in sub.columns:
                m_prod = sub[prod_col].astype(str).str.contains(search_term, case=False, na=False, regex=False).any()
                m_part = sub['Part Number'].astype(str).str.contains(search_term, case=False, na=False, regex=False).any() if 'Part Number' in sub.columns else False
                is_match = m_prod or m_part
            
            if sku >= 4: total_critical += 1
            elif sku == 0: total_kosong += 1
                
            matrix_info[(k, b)] = {
                'exist': True, 'sku_cnt': sku, 'filled': filled, 'usable_space': usable_space,
                'max_slot': max_slot, 'df_sub': sub, 'is_match': is_match
            }
    return matrix_info, total_critical, total_kosong, kolom_list, baris_list

matrix_info, total_critical, total_kosong, kolom_list, baris_list = process_matrix_data(df, search_query, product_col)

# ==========================================================
# MODAL POP-UP (VERSI LENGKAP DENGAN REKAP QTY)
# ==========================================================
@st.dialog("📦 Rincian Detail Rak & Konversi Stok", width="large")
def show_rack_detail(k, b, info):
    st.subheader(f"📍 Lokasi Racking: {k} - Baris {b}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Variasi SKU", f"{info['sku_cnt']} Jenis")
    c2.metric("Slot Fisik Terpakai", f"{info['filled']} / {info['max_slot']}")
    c3.metric("Space Kosong", f"{info['usable_space']} Slot")
    
    st.divider()
    
    if info['sku_cnt'] > 0:
        # 1. BACA MASTER PRODUK UNTUK RUMUS KONVERSI
        try:
            df_master = pd.read_csv("Master_Produk.csv", sep=";") if ";" in open("Master_Produk.csv").readline() else pd.read_csv("Master_Produk.csv", sep=",")
            df_master['Part Number Clean'] = df_master['Part Number'].astype(str).str.strip().str.upper()
        except: 
            df_master = pd.DataFrame()

        df_terisi = info['df_sub'][info['df_sub']['Part Number'].astype(str).str.strip() != ""]
        
        # 2. BUAT TABEL REKAPITULASI (PALLET UTUH & TOTAL PCS)
        rekap_data = []
        for part_num in df_terisi['Part Number'].astype(str).str.strip().unique():
            df_prod = df_terisi[df_terisi['Part Number'].astype(str).str.strip() == part_num]
            prod_name = df_prod[product_col].iloc[0] if product_col in df_prod.columns else "-"
            
            # Hitung Utuh
            jml_utuh = df_prod[~df_prod['Keterangan'].astype(str).str.contains('Pecahan|Eceran', case=False, na=False)].shape[0]
            
            # Hitung Pecahan/Eceran
            pecahan_rows = df_prod[df_prod['Keterangan'].astype(str).str.contains('Pecahan|Eceran', case=False, na=False)]
            val_pecahan = val_eceran = 0
            if not pecahan_rows.empty:
                ket_str = str(pecahan_rows['Keterangan'].iloc[0]).lower()
                mp = re.search(r'pecahan:\s*(\d+)', ket_str)
                if mp: val_pecahan = int(mp.group(1))
                me = re.search(r'eceran:\s*(\d+)', ket_str)
                if me: val_eceran = int(me.group(1))

            # Ambil Rumus dari Master
            ip = pb = ps = 0
            pnc = part_num.upper()
            if not df_master.empty and pnc in df_master['Part Number Clean'].values:
                mr = df_master[df_master['Part Number Clean'] == pnc].iloc[0]
                ip = float(mr.get('Isi 1 Pallet (pcs)', 0) or 0)
                pb = float(mr.get('Box / Pallet', 0) or 0)
                ps = float(mr.get('Sac / Pallet', 0) or 0)

            sc = "Dus" if pnc.endswith('D') else "Sak"
            pss = pb if pnc.endswith('D') else ps
            
            # Buat Teks Konversi
            if ip > 0:
                tot = (jml_utuh * ip) + (val_pecahan * pss) + val_eceran
                teks_rincian = f"{jml_utuh} Pallet * {ip:,.0f}"
                if val_pecahan > 0: teks_rincian += f" + {val_pecahan} {sc} * {pss:,.0f}"
                if val_eceran > 0: teks_rincian += f" + {val_eceran} Pcs"
                teks_rincian += f" = **Total {tot:,.0f} Pcs**"
            else:
                teks_rincian = f"{jml_utuh} Pallet"

            rekap_data.append({'Part Number': pnc, 'Nama Produk': prod_name, 'Pallet Utuh': jml_utuh, 'Konversi Total Pcs': teks_rincian})
        
        # TAMPILKAN TABEL REKAP
        st.markdown("#### 📊 Rekapitulasi Stok per Baris Rak")
        st.dataframe(pd.DataFrame(rekap_data), use_container_width=True, hide_index=True)
        st.write("") # Spasi
        
        # 3. TAMPILKAN TABEL RINCIAN MENTAH
        st.markdown("#### 📑 Rincian Posisi per Pallet")
        avail = [c for c in ['Pallet Ke', 'Part Number', 'Lot Number', product_col, 'Keterangan', 'Grand Total Pcs'] if c in df_terisi.columns]
        df_tampil = df_terisi[avail].copy()
        if 'Pallet Ke' in df_tampil.columns: df_tampil = df_tampil.sort_values(by='Pallet Ke', ascending=True)
        st.dataframe(df_tampil, use_container_width=True, hide_index=True)
        
    else:
        st.success("✅ Baris ini KOSONG. Siap digunakan!")

# ==========================================================
# RENDER METRIK & GRID
# ==========================================================
col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("Total Baris Aktif", "156 Baris")
col_m2.metric("Baris Kritis", f"{total_critical} Baris")
col_m3.metric("Baris Kosong", f"{total_kosong} Baris")
st.divider()

dynamic_css = """
.block-container { max-width: 98% !important; padding-top: 3.5rem !important; padding-bottom: 2rem !important; }
div[data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; }
div[data-testid="stColumn"] { padding-left: 2px !important; padding-right: 2px !important; }
div[data-testid="stColumn"]:nth-child(1) { display: flex; align-items: center; justify-content: center; }
div[class^="st-key-btn_"] button {
    aspect-ratio: 1/1 !important; width: 100% !important; min-width: 22px !important;
    padding: 0px !important; margin: 0px !important; border: 1px solid #475569 !important;
    border-radius: 4px !important; display: flex !important; align-items: center !important; font-weight: 900 !important;
}
div[class^="st-key-btn_"] button:hover { transform: scale(1.15); border: 2px solid #fff !important; z-index: 10; }
"""

color_map = {
    'match': {"bg": "#38bdf8", "txt": "#000000", "sel": []},
    'critical': {"bg": "#ef4444", "txt": "#ffffff", "sel": []},
    'warning': {"bg": "#fde047", "txt": "#000000", "sel": []},
    'ideal': {"bg": "#86efac", "txt": "#000000", "sel": []},
    'empty': {"bg": "#e2e8f0", "txt": "#94a3b8", "sel": []}
}

for k in kolom_list:
    for b in baris_list:
        info = matrix_info.get((k, b))
        if not info or not info['exist']: continue
        sku = info['sku_cnt']
        sel = f".st-key-btn_{k}_{b} button"
        if info['is_match']: color_map['match']['sel'].append(sel)
        elif sku >= 4: color_map['critical']['sel'].append(sel)
        elif sku == 3: color_map['warning']['sel'].append(sel)
        elif sku in [1, 2]: color_map['ideal']['sel'].append(sel)
        else: color_map['empty']['sel'].append(sel)

for group in color_map.values():
    if group['sel']: dynamic_css += f"\n{', '.join(group['sel'])} {{ background-color: {group['bg']} !important; color: {group['txt']} !important; }}"
st.markdown(f"<style>{dynamic_css}</style>", unsafe_allow_html=True)

def render_grid_area(title, start_baris, end_baris):
    st.markdown(f"### {title}")
    for k in kolom_list:
        cols = st.columns([0.6] + [1] * 16, gap="small")
        with cols[0]: st.markdown(f"<div style='font-weight:900;'>{k}</div>", unsafe_allow_html=True)
        for idx, b in enumerate(list(range(start_baris, end_baris + 1))):
            info = matrix_info[(k, b)]
            with cols[idx + 1]:
                if info['exist']:
                    lbl = str(info['usable_space']) if mode_tampilan == "Sisa Slot Kosong" else str(info['sku_cnt'])
                    if st.button(lbl, key=f"btn_{k}_{b}", use_container_width=True): show_rack_detail(k, b, info)

render_grid_area("📍 Area 1 (Rak 1 - 16)", 1, 16)
st.divider()
render_grid_area("📍 Area 2 (Rak 17 - 28)", 17, 28)
