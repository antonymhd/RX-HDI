import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import re
from datetime import datetime, timedelta

# ==========================================================
# 1. KONFIGURASI HALAMAN
# ==========================================================
st.set_page_config(page_title="Warehouse 2D Racking", page_icon="📦", layout="wide", initial_sidebar_state="expanded")

# ==========================================================
# 2. INIT FIREBASE (DATABASE UJI COBA)
# ==========================================================
NAMA_DATABASE = 'uji_coba_rak'

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================================
# 3. FUNGSI LOAD DATA (SMART CACHE - 5 MENIT)
# ==========================================================
@st.cache_data(ttl=300)
def load_data_from_firebase():
    docs = db.collection(NAMA_DATABASE).stream()
    semua_data = []
    
    for doc in docs:
        doc_data = doc.to_dict()
        if 'data' in doc_data:
            semua_data.extend(doc_data['data'])
            
    if not semua_data: return pd.DataFrame()
        
    df = pd.DataFrame(semua_data)
    for c in df.columns:
        if c.strip().lower() in ['palet ke', 'pallet ke']:
            df.rename(columns={c: 'Pallet Ke'}, inplace=True)
            
    for col in ['Baris', 'Pallet Ke']:
        if col in df.columns: 
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            
    return df

# ==========================================================
# 4. SIDEBAR & PENGATURAN
# ==========================================================
st.sidebar.header("🔄 Sinkronisasi Real-Time")
st.sidebar.info("Data dikunci selama 5 menit untuk menghemat kuota Firebase. Klik tombol di bawah jika butuh update instan.")

if st.sidebar.button("🔄 Tarik Data Gudang Terbaru", use_container_width=True, type="primary"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.header("👁️ Mode Tampilan Kotak")
mode_tampilan = st.sidebar.radio("Angka di dalam kotak rak mewakili:", ["Variasi SKU (Jenis Barang)", "Sisa Slot Kosong"])

# ==========================================================
# 5. MEMUAT DATA UTAMA & PENCARIAN (PRODUK / LOT)
# ==========================================================
st.title("📦 Visualisasi Grid Gudang (Live Monitor)")
st.caption(f"Layar pantau Read-Only. Terhubung ke database: **{NAMA_DATABASE}**")

df = load_data_from_firebase()

if df.empty or 'Kolom' not in df.columns:
    st.warning("Gudang kosong atau aplikasi sedang sinkronisasi. Harap tunggu...")
    st.stop()

product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'

st.sidebar.header("🔍 Pencarian Spesifik")
tipe_cari = st.sidebar.radio("Metode Pencarian:", ["Berdasarkan Produk", "Berdasarkan No. Lot"])
search_query, search_lot = "", ""

if tipe_cari == "Berdasarkan Produk":
    if product_col in df.columns:
        valid_mask = ~df['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan", "none", "<na>"])
        daftar_barang = sorted(df[valid_mask][product_col].dropna().astype(str).unique().tolist())
    else: daftar_barang = []
        
    pilihan_pencarian = st.sidebar.selectbox("Pilih Produk:", options=["-- Tampilkan Semua --"] + daftar_barang)
    search_query = "" if pilihan_pencarian == "-- Tampilkan Semua --" else pilihan_pencarian
else:
    if 'Lot Number' in df.columns:
        valid_mask = ~df['Lot Number'].astype(str).str.strip().str.lower().isin(["", "nan", "none", "<na>", "-", "0"])
        daftar_lot = sorted(df[valid_mask]['Lot Number'].dropna().astype(str).unique().tolist())
    else: daftar_lot = []
        
    pilihan_lot = st.sidebar.selectbox("Pilih No. Lot:", options=["-- Tampilkan Semua --"] + daftar_lot)
    search_lot = "" if pilihan_lot == "-- Tampilkan Semua --" else pilihan_lot

# ==========================================================
# 6. LOGIKA MATRIKS RAK (MEMBACA KAPASITAS BOX & KARUNG)
# ==========================================================
def is_rack_exist(kolom, baris):
    if kolom == 'F' and baris < 5: return False
    if kolom == 'G' and baris < 17: return False
    return True

def process_matrix_data(df, search_term, search_lot_term, prod_col):
    kolom_list = ['G', 'F', 'E', 'D', 'C', 'B', 'A']
    baris_list = list(range(1, 29))
    matrix_info = {}
    
    total_critical, total_warning, total_ideal, total_kosong = 0, 0, 0, 0
    total_slot_ideal, total_slot_warning = 0, 0
    
    for k in kolom_list:
        for b in baris_list:
            if not is_rack_exist(k, b):
                matrix_info[(k, b)] = {'exist': False}
                continue
                
            sub = df[(df['Kolom'] == k) & (df['Baris'] == b)]
            is_all_box, filled, sku, is_match = False, 0, 0, False
            
            if 'Part Number' in sub.columns:
                p_series = sub['Part Number'].astype(str).str.strip()
                valid_mask = ~p_series.str.lower().isin(["", "nan", "none", "<na>"])
                p_valid = p_series[valid_mask]
                
                filled = int(valid_mask.sum())
                sku = len(p_valid.unique())
                
                if not p_valid.empty:
                    is_all_box = bool(p_valid.str.upper().str.endswith(('D', 'G')).all())
                    
                if search_term:
                    m_part = p_series.str.contains(search_term, case=False, na=False, regex=False).any()
                    m_prod = sub[prod_col].astype(str).str.contains(search_term, case=False, na=False, regex=False).any() if prod_col in sub.columns else False
                    is_match = bool(m_part or m_prod)
                elif search_lot_term:
                    if 'Lot Number' in sub.columns:
                        is_match = sub['Lot Number'].astype(str).str.strip().str.contains(search_lot_term, case=False, na=False, regex=False).any()
            
            max_slot = int(32 if b <= 16 else 46) if is_all_box else int(31 if b <= 16 else 44)
            usable_space = max(0, max_slot - filled)
            
            if sku >= 3: total_critical += 1
            elif sku == 2: 
                total_warning += 1
                if usable_space > 1: total_slot_warning += usable_space
            elif sku == 1:
                total_ideal += 1
                if usable_space > 1: total_slot_ideal += usable_space
            elif sku == 0: total_kosong += 1
                
            matrix_info[(k, b)] = {'exist': True, 'sku_cnt': sku, 'filled': filled, 'usable_space': usable_space, 'max_slot': max_slot, 'df_sub': sub, 'is_match': is_match}
            
    return matrix_info, total_critical, total_warning, total_ideal, total_kosong, total_slot_ideal, total_slot_warning, kolom_list, baris_list

matrix_info, total_critical, total_warning, total_ideal, total_kosong, total_slot_ideal, total_slot_warning, kolom_list, baris_list = process_matrix_data(df, search_query, search_lot, product_col)

# ----------------------------------------------------------
# FITUR PANTAU RAK OVERLIMIT / ABNORMAL (BAYANGAN)
# ----------------------------------------------------------
st.sidebar.divider()
st.sidebar.header("🚨 Peringatan Rak Overlimit")
st.sidebar.caption("Memantau rak yang jumlah fisiknya melebihi kapasitas maksimal sistem. Wajib cek lapangan!")

bayangan_data = []
rak_bermasalah = set()

for (k, b), info in matrix_info.items():
    if info['exist'] and not info['df_sub'].empty:
        df_sub = info['df_sub']
        if 'Catatan' in df_sub.columns:
            anomali = df_sub[df_sub['Catatan'].astype(str).str.contains('BAYANGAN', case=False, na=False)]
            if not anomali.empty:
                rak_bermasalah.add(f"{k}-{b}")
                for _, row in anomali.iterrows():
                    bayangan_data.append(row.to_dict())

if bayangan_data:
    list_rak = ", ".join(sorted(list(rak_bermasalah)))
    st.sidebar.error(f"⚠️ **Ditemukan {len(rak_bermasalah)} Rak Overlimit:**\n\n{list_rak}")
    
    df_bayangan = pd.DataFrame(bayangan_data)
    cols_awal = ['Kolom', 'Baris', 'Pallet Ke', 'Part Number', 'Nama Produk', 'Lot Number', 'Keterangan', 'Catatan']
    cols_tersedia = [c for c in cols_awal if c in df_bayangan.columns]
    df_bayangan = df_bayangan[cols_tersedia]
    
    if all(c in df_bayangan.columns for c in ['Kolom', 'Baris', 'Pallet Ke']):
        df_bayangan['Baris'] = pd.to_numeric(df_bayangan['Baris'], errors='coerce')
        df_bayangan['Pallet Ke'] = pd.to_numeric(df_bayangan['Pallet Ke'], errors='coerce')
        df_bayangan = df_bayangan.sort_values(by=['Kolom', 'Baris', 'Pallet Ke'])
        
    csv = df_bayangan.to_csv(index=False, sep=";").encode('utf-8-sig')
    st.sidebar.download_button(
        label="📥 Unduh Daftar Pallet Bayangan",
        data=csv,
        file_name=f"Cek_Lapangan_Overlimit_{(datetime.utcnow() + timedelta(hours=7)).strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        type="primary"
    )
else:
    st.sidebar.success("✅ Seluruh rak dalam batas kapasitas normal. Tidak ada pallet bayangan.")

# ==========================================================
# 7. POP-UP DETAIL RAK (KALKULASI Pcs & STYLING BAYANGAN)
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
            try: df_master = pd.read_csv("Master_Produk.csv", sep=";", encoding='utf-8-sig')
            except: df_master = pd.read_csv("Master_Produk.csv", sep=",", encoding='utf-8-sig')
            df_master.columns = df_master.columns.str.strip()
            df_master['Part Number Clean'] = df_master['Part Number'].astype(str).str.strip().str.upper()
        except: df_master = pd.DataFrame()

        df_terisi = info['df_sub'][~info['df_sub']['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan", "none", "<na>"])]
        
        rekap_data = []
        for part_num in df_terisi['Part Number'].astype(str).str.strip().unique():
            df_prod = df_terisi[df_terisi['Part Number'].astype(str).str.strip() == part_num]
            prod_name = str(df_prod[product_col].dropna().values[0]) if product_col in df_prod.columns and len(df_prod[product_col].dropna().values) > 0 else "-"
            
            jml_utuh, val_pecahan, val_eceran = 0, 0, 0
            for _, row in df_prod.iterrows():
                ket_str = str(row.get('Keterangan', '')).lower()
                if 'pecahan' not in ket_str and 'eceran' not in ket_str: jml_utuh += 1
                else:
                    mp = re.search(r'pecahan:\s*(\d+)', ket_str)
                    if mp: val_pecahan += int(mp.group(1))
                    else:
                        nums = re.findall(r'\d+', ket_str)
                        if nums and 'pecahan' in ket_str: val_pecahan += int(nums[0])
                    me = re.search(r'eceran:\s*(\d+)', ket_str)
                    if me: val_eceran += int(me.group(1))

            ip, pb, ps = 0, 0, 0
            pnc = str(part_num).strip().upper() 
            if not df_master.empty and 'Part Number Clean' in df_master.columns and pnc in df_master['Part Number Clean'].values:
                mr = df_master[df_master['Part Number Clean'] == pnc].iloc[0]
                ip = float(pd.to_numeric(mr.get('Isi 1 Pallet (pcs)', 0), errors='coerce') or 0)
                pb = float(pd.to_numeric(mr.get('Box / Pallet', 0), errors='coerce') or 0)
                ps = float(pd.to_numeric(mr.get('Sac / Pallet', 0), errors='coerce') or 0)

            sc = "Dus" if pnc.endswith('D') else "Sak"
            pss = pb if pnc.endswith('D') else ps
            
            if ip > 0:
                tot = (jml_utuh * ip) + (val_pecahan * pss) + val_eceran
                teks_rincian = f"{jml_utuh} Pallet * {ip:,.0f}"
                if val_pecahan > 0: teks_rincian += f" + {val_pecahan} {sc} * {pss:,.0f}"
                if val_eceran > 0: teks_rincian += f" + {val_eceran} Pcs"
                teks_rincian += f" = **Total {tot:,.0f} Pcs**"
            else: teks_rincian = f"{jml_utuh} Pallet"

            rekap_data.append({'Part Number': pnc, 'Nama Produk': prod_name, 'Pallet Utuh': jml_utuh, 'Konversi Total Pcs': teks_rincian})
        
        st.markdown("#### 📊 Rekapitulasi Stok (Otomatis)")
        st.dataframe(pd.DataFrame(rekap_data), use_container_width=True, hide_index=True)
        st.write("") 
        
        st.markdown("#### 📑 Rincian Posisi per Pallet")
        avail = [c for c in ['Pallet Ke', 'Part Number', 'Lot Number', product_col, 'Keterangan', 'Catatan'] if c in df_terisi.columns]
        df_tampil = df_terisi[avail].copy()
        if 'Pallet Ke' in df_tampil.columns: df_tampil = df_tampil.sort_values(by='Pallet Ke', ascending=True)
            
        def highlight_bayangan(row):
            cat = str(row.get('Catatan', '')).upper()
            if 'BAYANGAN' in cat:
                return ['background-color: #fef2f2; color: #991b1b; font-weight: bold;'] * len(row)
            elif 'BOOKED' in cat:
                return ['background-color: #eff6ff; color: #1e3a8a; font-weight: bold; border-left: 4px solid #2563eb;'] * len(row)
            return [''] * len(row)
            
        styled_df = df_tampil.style.apply(highlight_bayangan, axis=1)
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else:
        st.success("✅ Rak Kosong. Aman untuk diisi.")

# ==========================================================
# 8. RENDER METRIK & GRID UI (WARNA AMAN CSS)
# ==========================================================
col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
total_baris_hitung = total_ideal + total_warning + total_critical + total_kosong

col_m1.metric("Total Baris Aktif", f"{total_baris_hitung} Baris")
col_m2.metric("🟢 Rak Ideal (1 SKU)", f"{total_ideal} Baris", f"{total_slot_ideal} Slot Siap Isi", delta_color="normal")
col_m3.metric("🟡 Rak Campur (2 SKU)", f"{total_warning} Baris", f"{total_slot_warning} Slot Siap Isi", delta_color="normal")
col_m4.metric("🔴 Rak Kritis (>= 3 SKU)", f"{total_critical} Baris", "Fokus Reshuffle", delta_color="off")
col_m5.metric("⚪ Rak Kosong Bersih", f"{total_kosong} Baris")
st.divider()

css_block_1 = ".block-container { max-width: 98% !important; padding-top: 2rem !important; padding-bottom: 2rem !important; }"
css_block_2 = 'div[data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; }'
css_block_3 = 'div[data-testid="stColumn"] { padding-left: 2px !important; padding-right: 2px !important; }'
css_block_4 = 'div[data-testid="stColumn"]:nth-child(1) { display: flex; align-items: center; justify-content: center; }'
css_btn = '''
div[class^="st-key-btn_"] button {
    aspect-ratio: 1/1 !important; 
    width: 100% !important; 
    min-width: 20px !important;
    padding: 0px !important; margin: 0px !important; border: 1px solid #475569 !important;
    border-radius: 4px !important; display: flex !important; align-items: center !important; justify-content: center !important;
    font-weight: 900 !important;
}
div[class^="st-key-btn_"] button:hover { transform: scale(1.15); border: 2px solid #fff !important; z-index: 10; }
div[class^="st-key-btn_"] button p { margin: 0 !important; line-height: 1 !important; font-size: clamp(9px, 1.2vw, 14px) !important; }
