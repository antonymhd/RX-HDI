import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import re

st.set_page_config(
    page_title="Warehouse 2D Racking",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================================
# 1. INIT FIREBASE (Sesuai dengan Rahasia Streamlit)
# ==========================================================
NAMA_DATABASE = 'uji_coba_rak'

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================================
# 2. LOAD DATA DENGAN SMART CACHE (Super Hemat Kuota)
# ==========================================================
# Kunci memori selama 5 menit. Jika ada mutasi baru, cukup klik "Refresh Real-Time"
@st.cache_data(ttl=300) 
def load_data_from_firebase():
    docs = db.collection(NAMA_DATABASE).stream()
    semua_data = []
    
    # Ekstrak data dari struktur "Borongan" (Kolom_A -> data: [...])
    for doc in docs:
        doc_data = doc.to_dict()
        if 'data' in doc_data:
            semua_data.extend(doc_data['data'])
            
    if not semua_data:
        return pd.DataFrame()
        
    df = pd.DataFrame(semua_data)
    
    # Standarisasi kolom
    for c in df.columns:
        if c.strip().lower() in ['palet ke', 'pallet ke']:
            df.rename(columns={c: 'Pallet Ke'}, inplace=True)
            
    for col in ['Baris', 'Pallet Ke']:
        if col in df.columns: 
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            
    return df

# ==========================================================
# 3. SIDEBAR PENGATURAN
# ==========================================================
st.sidebar.header("🔄 Sinkronisasi Real-Time")
st.sidebar.info("Untuk melindungi kuota Firebase (Mencegah Limit), data gudang dikunci di memori selama 5 menit. Gunakan tombol di bawah jika Anda butuh data paling akurat detik ini juga.")

if st.sidebar.button("🔄 Tarik Data Gudang Terbaru", use_container_width=True, type="primary"):
    st.cache_data.clear()
    st.success("Menarik data ter-update dari server (Memakan 7 Reads)...")
    st.rerun()

st.sidebar.divider()

st.sidebar.header("👁️ Mode Tampilan Grid")
mode_tampilan = st.sidebar.radio(
    "Angka pada kotak rak menunjukkan:",
    ["Variasi SKU (Jenis Barang)", "Sisa Slot Kosong"]
)

# ==========================================================
# 4. MEMUAT DATA
# ==========================================================
st.title("📦 Visualisasi Grid Gudang (LIVE)")
st.caption(f"Menampilkan kondisi asli stok di database: {NAMA_DATABASE}")

df = load_data_from_firebase()
if df.empty or 'Kolom' not in df.columns:
    st.warning("Gudang saat ini masih kosong atau aplikasi sedang sinkronisasi data...")
    st.stop()

product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'

# ==========================================================
# PENCARIAN & FILTER
# ==========================================================
st.sidebar.header("🔍 Pencarian & Filter")
if product_col in df.columns:
    daftar_barang = sorted(df[~df['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan"])][product_col].dropna().astype(str).unique().tolist())
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
                p_nums_clean = p_nums[~p_nums.str.lower().isin(["", "nan"])]
                if not p_nums_clean.empty: is_all_box = p_nums_clean.str.endswith(('D', 'G')).all()
            
            max_slot = (32 if b <= 16 else 46) if is_all_box else (31 if b <= 16 else 44)
            prods = sub['Part Number'].unique() if 'Part Number' in sub.columns else []
            
            prods_clean = [p for p in prods if str(p).strip().lower() not in ["", "nan"]]
            sku = len(prods_clean)
            
            filled = sub['Part Number'].apply(lambda x: str(x).strip().lower() not in ["", "nan"] and pd.notna(x)).sum() if 'Part Number' in sub.columns else 0
            usable_space = max(0, max_slot - filled)
            
            is_match = False
            if search_term and prod_col in sub.columns:
                m_prod = sub[prod_col].astype(str).str.contains(search_term, case=False, na=False, regex=False).any()
                m_part = sub['Part Number'].astype(str).str.contains(search_term, case=False, na=False, regex=False).any() if 'Part Number' in sub.columns else False
                is_match = m_prod or m_part
            
            if sku >= 4: total_critical += 1
            elif sku == 0: total_kosong += 1
                
            matrix_info[(k, b)] = {'exist': True, 'sku_cnt': sku, 'filled': filled, 'usable_space': usable_space, 'max_slot': max_slot, 'df_sub': sub, 'is_match': is_match}
            
    return matrix_info, total_critical, total_kosong, kolom_list, baris_list

matrix_info, total_critical, total_kosong, kolom_list, baris_list = process_matrix_data(df, search_query, product_col)

# ==========================================================
# MODAL POP-UP (REKAP QTY & KONVERSI LENGKAP)
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
        # BACA MASTER PRODUK UNTUK RUMUS KONVERSI
        try:
            try: df_master = pd.read_csv("Master_Produk.csv", sep=";")
            except: df_master = pd.read_csv("Master_Produk.csv", sep=",")
            df_master['Part Number Clean'] = df_master['Part Number'].astype(str).str.strip().str.upper()
        except: 
            df_master = pd.DataFrame()

        df_terisi = info['df_sub'][~info['df_sub']['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan"])]
        
        # BUAT TABEL REKAPITULASI
        rekap_data = []
        for part_num in df_terisi['Part Number'].astype(str).str.strip().unique():
            df_prod = df_terisi[df_terisi['Part Number'].astype(str).str.strip() == part_num]
            
            prod_name = "-"
            if product_col in df_prod.columns and not df_prod.empty:
                valid_names = df_prod[product_col].dropna().values
                if len(valid_names) > 0: prod_name = str(valid_names[0])
            
            jml_utuh = df_prod[~df_prod['Keterangan'].astype(str).str.contains('Pecahan|Eceran', case=False, na=False)].shape[0]
            pecahan_rows = df_prod[df_prod['Keterangan'].astype(str).str.contains('Pecahan|Eceran', case=False, na=False)]
            
            val_pecahan = val_eceran = 0
            if not pecahan_rows.empty:
                ket_str = str(pecahan_rows['Keterangan'].iloc[0]).lower()
                mp = re.search(r'pecahan:\s*(\d+)', ket_str)
                if mp: val_pecahan = int(mp.group(1))
                else:
                    nums = re.findall(r'\d+', ket_str)
                    if nums and 'pecahan' in ket_str: val_pecahan = int(nums[0])
                
                me = re.search(r'eceran:\s*(\d+)', ket_str)
                if me
