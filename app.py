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
    daftar_barang = sorted(df[~df['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan"])][product_col].dropna().astype(str).unique().tolist())
else:
    daftar_barang = []
    
pilihan_pencarian = st.sidebar.selectbox("Cari Posisi Barang:", options=["-- Tampilkan Semua --"] + daftar_barang)
search_query = "" if pilihan_pencarian == "-- Tampilkan Semua --" else pilihan_pencarian

# ==========================================================
# 5. LOGIKA MATRIKS RAK
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
        # BACA MASTER PRODUK UNTUK RUMUS KONVERSI
        try:
            try: df_master = pd.read_csv("Master_Produk.csv", sep=";")
            except: df_master = pd.read_csv("Master_Produk.csv", sep=",")
            df_master['Part Number Clean'] = df_master['Part Number'].astype(str).str.strip().str.upper()
        except: 
            df_master = pd.DataFrame()

        df_terisi = info['df_sub'][~info['df_sub']['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan"])]
        
        # BUAT TABEL REKAPITULASI KONVERSI PCS
        rekap_data = []
        for part_num in df_terisi['Part Number'].astype(str).str.strip().unique():
            df_prod = df_terisi[df_terisi['Part Number'].astype(str).str.strip() == part_num]
            
            prod_name = "-"
            if product_col in df_prod.columns and not df_prod.empty:
                valid_names = df_prod[product_col].dropna().values
                if len(valid_names) > 0: prod_name = str(valid_names[0])
            
            jml_utuh = 0
            val_pecahan = 0
            val_eceran = 0
            
            # AKUMULASI SEMUA SLOT UNTUK PART NUMBER INI
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

            # TARIK REFERENSI MASTER (Isi Pallet & Isi Dus/Sak)
            ip = pb = ps = 0
            pnc = str(part_num).strip().upper() 
            if not df_master.empty and pnc in df_master['Part Number Clean'].values:
                mr = df_master[df_master['Part Number Clean'] == pnc].iloc[0]
                ip = float(mr.get('Isi 1 Pallet (pcs)', 0) or 0)
                pb = float(mr.get('Box / Pallet', 0) or 0)
                ps = float(mr.get('Sac / Pallet', 0) or 0)

            sc = "Dus" if pnc.endswith('D') else "Sak"
            pss = pb if pnc.endswith('D') else ps
            
            # MATEMATIKA TOTAL PCS BERDASARKAN RUMUS
            if ip > 0:
                tot = (jml_utuh * ip) + (val_pecahan * pss) + val_eceran
                teks_rincian = f"{jml_utuh} Pallet * {ip:,.0f}"
                if val_pecahan > 0: teks_rincian += f" + {val_pecahan} {sc} * {pss:,.0f}"
                if val_eceran > 0: teks_rincian += f" + {val_eceran} Pcs"
                teks_rincian += f" = **Total {tot:,.0f} Pcs**"
            else:
                teks_rincian = f"{jml_utuh} Pallet"

            rekap_data.append({'Part Number': pnc, 'Nama Produk': prod_name, 'Pallet Utuh': jml_utuh, 'Konversi Total Pcs': teks_rincian})
        
        st.markdown("#### 📊 Rekapitulasi Stok (Otomatis)")
        st.dataframe(pd.DataFrame(rekap_data), use_container_width=True, hide_index=True)
        st.write("") 
        
        st.markdown("#### 📑 Rincian Posisi per Pallet")
        avail = [c for c in ['Pallet Ke', 'Part Number', 'Lot Number', product_col, 'Keterangan'] if c in df_terisi.columns]
        df_tampil = df_terisi[avail].copy()
        if 'Pallet Ke' in df_tampil.columns: df_tampil = df_tampil.sort_values(by='Pallet Ke', ascending=True)
        st.dataframe(df_tampil, use_container_width=True, hide_index=True)
        
    else:
        st.success("✅ Rak Kosong. Aman untuk diisi.")

# ==========================================================
# 7. RENDER METRIK & GRID UI
# ==========================================================
col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("Total Baris Aktif", "156 Baris")
col_m2.metric("Rak Kritis (>= 4 SKU)", f"{total_critical} Baris")
col_m3.metric("Rak Kosong Bersih", f"{total_kosong} Baris")
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
    'match': {"bg": "#38bdf
