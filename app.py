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
# 1. INIT FIREBASE
# ==========================================================
NAMA_DATABASE = 'uji_coba_rak'

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================================
# 2. LOAD DATA DENGAN SMART CACHE (Hanya 7 Reads!)
# ==========================================================
@st.cache_data(ttl=300) 
def load_data_from_firebase():
    docs = db.collection(NAMA_DATABASE).stream()
    semua_data = []
    
    for doc in docs:
        doc_data = doc.to_dict()
        if 'data' in doc_data:
            semua_data.extend(doc_data['data'])
            
    if not semua_data:
        return pd.DataFrame()
        
    df = pd.DataFrame(semua_data)
    
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
st.sidebar.info("Data dikunci selama 5 menit untuk menghemat kuota Firebase. Klik tombol di bawah jika butuh update instan.")

if st.sidebar.button("🔄 Tarik Data Gudang Terbaru", use_container_width=True, type="primary"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()

st.sidebar.header("👁️ Mode Tampilan Kotak")
mode_tampilan = st.sidebar.radio(
    "Angka di dalam kotak rak mewakili:",
    ["Variasi SKU (Jenis Barang)", "Sisa Slot Kosong"]
)

# ==========================================================
# 4. MEMUAT DATA & FILTER PENCARIAN
# ==========================================================
st.title("📦 Visualisasi Grid Gudang (Live Monitor)")
st.caption(f"Layar pantau Read-Only. Terhubung ke: {NAMA_DATABASE}")

df = load_data_from_firebase()
if df.empty or 'Kolom' not in df.columns:
    st.warning("Gudang kosong atau aplikasi sedang sinkronisasi. Harap tunggu...")
    st.stop()

product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'

st.sidebar.header("🔍 Cari Barang")
if product_col in df.columns:
    # Filter aman dari error tipe data
    valid_names = df[~df['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan", "none", "<na>"])]
    daftar_barang = sorted(valid_names[product_col].dropna().astype(str).unique().tolist()) if product_col in valid_names.columns else []
else:
    daftar_barang = []
    
pilihan_pencarian = st.sidebar.selectbox("Cari Posisi Barang:", options=["-- Tampilkan Semua --"] + daftar_barang)
search_query = "" if pilihan_pencarian == "-- Tampilkan Semua --" else pilihan_pencarian

# ==========================================================
# 5. LOGIKA MATRIKS RAK (ANTI TYPE-ERROR)
# ==========================================================
def is_rack_exist(kolom, baris):
    if kolom == 'F' and baris < 5: return False
    if kolom == 'G' and baris < 17: return False
    return True

def process_matrix_data(df, search_term, prod_col):
    kolom_list = ['G', 'F', 'E', 'D', 'C', 'B', 'A']
    baris_list = list(range(1, 29))
    matrix_info = {}
    total_critical = 0
    total_kosong = 0
    
    for k in kolom_list:
        for b in baris_list:
            if not is_rack_exist(k, b):
                matrix_info[(k, b)] = {'exist': False}
                continue
                
            sub = df[(df['Kolom'] == k) & (float(b) == pd.to_numeric(df['Baris'], errors='coerce'))]
            
            is_all_box = False
            filled = 0
            sku = 0
            is_match = False
            
            if 'Part Number' in sub.columns:
                # 100% Pengamanan Tipe Data (Memaksa jadi string dan integer tulen)
                p_series = sub['Part Number'].astype(str).str.strip()
                valid_mask = ~p_series.str.lower().isin(["", "nan", "none", "<na>"])
                p_valid = p_series[valid_mask]
                
                filled = int(valid_mask.sum())
                sku = len(p_valid.unique())
                
                if not p_valid.empty:
                    is_all_box = bool(p_valid.str.upper().str.endswith(('D', 'G')).all())
                    
                if search_term:
                    m_part = p_series.str.contains(search_term, case=False, na=False, regex=False).any()
                    m_prod = False
                    if prod_col in sub.columns:
                        m_prod = sub[prod_col].astype(str).str.contains(search_term, case=False, na=False, regex=False).any()
                    is_match = bool(m_part or m_prod)
            
            # Kunci hasil jadi integer bulat
            max_slot = int(32 if b <= 16 else 46) if is_all_box else int(31 if b <= 16 else 44)
            usable_space = max(0, max_slot - filled)
            
            if sku >= 4: total_critical += 1
            elif sku == 0: total_kosong += 1
                
            matrix_info[(k, b)] = {
                'exist': True, 
                'sku_cnt': sku, 
                'filled': filled, 
                'usable_space': usable_space, 
                'max_slot': max_slot, 
                'df_sub': sub, 
                'is_match': is_match
            }
            
    return matrix_info, total_critical, total_kosong, kolom_list, baris_list

matrix_info, total_critical, total_kosong, kolom_list, baris_list = process_matrix_data(df, search_query, product_col)

# ==========================================================
# 6. POP-UP DETAIL RAK (KONVERSI AKURAT)
# ==========================================================
@st.dialog("📦 Rincian Detail Rak", width="large")
def show_rack_detail(k, b, info):
    st.subheader(f"📍 Lokasi Racking: {k} - Baris {b}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Variasi SKU", f"{info['sku_cnt']} Jenis")
    c2.metric("Slot Fisik Terpakai", f"{info['filled']} / {info['max_slot']}")
    c3.metric("Space Kosong", f"{info['usable_space']} Slot")
    
    st.divider()
    
    if info['sku_cnt'] > 0:
        try:
            try: df_master = pd.read_csv("Master_Produk.csv", sep=";")
            except: df_master = pd.read_csv("Master_Produk.csv", sep=",")
            df_master['Part Number Clean'] = df_master['Part Number'].astype(str).str.strip().str.upper()
        except: 
            df_master = pd.DataFrame()

        # Filter Data Terisi Aman
        df_terisi = info['df_sub'][~info['df_sub']['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan", "none", "<na>"])]
        
        rekap_data = []
        for part_num in df_terisi['Part Number'].astype(str).str.strip().unique():
            df_prod = df_terisi[df_terisi['Part Number'].astype(str).str.strip() == part_num]
            
            prod_name = "-"
            if product_col in df_prod.columns and not df_prod.empty:
                valid_names = df_prod[product_col].dropna().values
                if len(valid_names) > 0: prod_name = str(valid_names[0])
            
            jml_utuh = 0; val_pecahan = 0; val_eceran = 0
            
            for _, row in df_prod.iterrows():
                ket_str = str(row.get('Keterangan', '')).lower()
                is_pecahan = 'pecahan' in ket_str or 'eceran' in ket_str
                
                if not is_pecahan:
                    jml_utuh += 1
                else:
                    mp = re.search(r'pecahan:\s*(\d+)', ket_str)
                    if mp: val_pecahan += int(mp.group(1))
                    else:
                        nums = re.findall(r'\d+', ket_str)
                        if nums and 'pecahan' in ket_str: val_pecahan += int(nums[0])
                        
                    me = re.search(r'eceran:\s*(\d+)', ket_str)
                    if me: val_eceran += int(me.group(1))

            ip = 0; pb = 0; ps = 0
            pnc = str(part_num).strip().upper() 
            if not df_master.empty and 'Part Number Clean' in df_master.columns and pnc in df_master['Part Number Clean'].values:
                mr = df_master[df_master['Part Number Clean'] == pnc].iloc[0]
                
                ip = pd.to_numeric(mr.get('Isi 1 Pallet (pcs)', 0), errors='coerce')
                ip = 0 if pd.isna(ip) else float(ip)
                
                pb = pd.to_numeric(mr.get('Box / Pallet', 0), errors='coerce')
                pb = 0 if pd.isna(pb) else float(pb)
                
                ps = pd.to_numeric(mr.get('Sac / Pallet', 0
