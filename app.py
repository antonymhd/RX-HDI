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
                'exist': True, 'sku_cnt': sku, 'filled': filled,
