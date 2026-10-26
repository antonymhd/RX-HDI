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
st.caption(f"Layar pantau Read-Only. Terhubung ke database: {NAMA_DATABASE}")

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
col_m4.metric("🔴 Rak Kritis (>= 3 SKU)", f"{total_critical} Baris", "Hindari Inbound", delta_color="off")
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
@media (max-width: 800px) { div[data-testid="stColumn"] { padding-left: 1px !important; padding-right: 1px !important; } div[class^="st-key-btn_"] button { min-width: 15px !important; border-radius: 2px !important; } div[data-testid="stColumn"]:nth-child(1) { font-size: 11px !important; } }
'''

dynamic_css = f"{css_block_1}\n{css_block_2}\n{css_block_3}\n{css_block_4}\n{css_btn}"
color_map = {'match': {"bg": "deepskyblue", "txt": "black", "sel": []}, 'critical': {"bg": "crimson", "txt": "white", "sel": []}, 'warning': {"bg": "gold", "txt": "black", "sel": []}, 'ideal': {"bg": "palegreen", "txt": "black", "sel": []}, 'empty': {"bg": "gainsboro", "txt": "gray", "sel": []}}

for k in kolom_list:
    for b in baris_list:
        info = matrix_info.get((k, b))
        if not info or not info['exist']: continue
        sku = info['sku_cnt']
        sel = f".st-key-btn_{k}_{b} button"
        
        if info['is_match']: color_map['match']['sel'].append(sel)
        elif sku >= 3: color_map['critical']['sel'].append(sel)
        elif sku == 2: color_map['warning']['sel'].append(sel)
        elif sku == 1: color_map['ideal']['sel'].append(sel)
        else: color_map['empty']['sel'].append(sel)

for group in color_map.values():
    if group['sel']: dynamic_css += f"\n{', '.join(group['sel'])} {{ background-color: {group['bg']} !important; color: {group['txt']} !important; }}"

st.markdown(f"<style>{dynamic_css}</style>", unsafe_allow_html=True)

def render_grid_area(title, start_baris, end_baris):
    st.markdown(f"### {title}")
    header_cols = st.columns([0.6] + [1] * 16, gap="small")
    with header_cols[0]: st.empty() 
        
    for idx, b in enumerate(list(range(start_baris, end_baris + 1))):
        with header_cols[idx + 1]: st.markdown(f"<div style='text-align:center; font-weight:900; font-size:14px; color:#94a3b8; margin-bottom:4px;'>{b}</div>", unsafe_allow_html=True)
    
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

# ==========================================================
# 9. DAFTAR LOKASI RAK & SARAN RELOKASI (BERBASIS POSISI UJUNG & LOT TERMUDA)
# ==========================================================
st.divider()

def group_by_block(rack_list):
    if not rack_list: return "Tidak ada rak."
    grouped = {}
    for r in rack_list:
        k, b = r.split('-')
        if k not in grouped: grouped[k] = []
        grouped[k].append(r)
    
    res = ""
    for k in sorted(grouped.keys()):
        res += f"**Blok {k}:** {', '.join(grouped[k])}<br>"
    return res

def parse_lot_date(lot_str):
    cleaned = str(lot_str).strip()
    if len(cleaned) >= 6:
        date_str = cleaned[-6:]
        try:
            day = int(date_str[0:2])
            month = int(date_str[2:4])
            year = int('20' + date_str[4:6])
            return datetime(year, month, day)
        except:
            return datetime(1900, 1, 1)
    return datetime(1900, 1, 1)

list_merah, list_kuning, list_hijau, list_abu = [], [], [], []
rack_profiles = {}

for k in kolom_list:
    for b in baris_list:
        info = matrix_info.get((k, b))
        if info and info['exist']:
            sku = info['sku_cnt']
            lokasi = f"{k}-{b}"
            
            if sku >= 3: list_merah.append(lokasi)
            elif sku == 2: list_kuning.append(lokasi)
            elif sku == 1: list_hijau.append(lokasi)
            elif sku == 0: list_abu.append(lokasi)
            
            df_sub = info['df_sub']
            pallets_data = []
            if 'Part Number' in df_sub.columns:
                valid_df = df_sub[~df_sub['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan", "none", "<na>"])]
                for _, row in valid_df.iterrows():
                    pn = str(row['Part Number']).strip().upper()
                    prod = str(row.get('Nama Produk', pn)).strip()
                    lot = str(row.get('Lot Number', '')).strip()
                    pallet_ke = int(row.get('Pallet Ke', 0))
                    lot_date = parse_lot_date(lot)
                    
                    pallets_data.append({
                        'part_number': pn,
                        'name': prod,
                        'lot': lot,
                        'pallet_ke': pallet_ke,
                        'lot_date': lot_date
                    })
                    
            rack_profiles[(k, b)] = {'sku_cnt': sku, 'usable': info['usable_space'], 'pallets': pallets_data}

st.markdown("### 📋 Daftar Lokasi Berdasarkan Status Rak (Dikelompokkan per Blok)")

col_list1, col_list2, col_list3, col_list4 = st.columns(4)
with col_list1:
    st.markdown(f"**⚪ Kosong ({len(list_abu)} Rak)**")
    st.markdown(f"<div style='background-color: #f8fafc; padding: 10px; border-radius: 6px; font-size: 13px; color: #475569; border: 1px solid #cbd5e1;'>{group_by_block(list_abu)}</div>", unsafe_allow_html=True)
with col_list2:
    st.markdown(f"**🟢 Ideal ({len(list_hijau)} Rak)**")
    st.markdown(f"<div style='background-color: #f0fdf4; padding: 10px; border-radius: 6px; font-size: 13px; color: #166534; border: 1px solid #bbf7d0;'>{group_by_block(list_hijau)}</div>", unsafe_allow_html=True)
with col_list3:
    st.markdown(f"**🟡 Campur ({len(list_kuning)} Rak)**")
    st.markdown(f"<div style='background-color: #fefce8; padding: 10px; border-radius: 6px; font-size: 13px; color: #854d0e; border: 1px solid #fef08a;'>{group_by_block(list_kuning)}</div>", unsafe_allow_html=True)
with col_list4:
    st.markdown(f"**🔴 Kritis ({len(list_merah)} Rak)**")
    st.markdown(f"<div style='background-color: #fef2f2; padding: 10px; border-radius: 6px; font-size: 13px; color: #991b1b; border: 1px solid #fecaca;'>{group_by_block(list_merah)}</div>", unsafe_allow_html=True)

st.divider()
st.markdown("### 💡 Saran Relokasi Cerdas (Fokus Posisi Ujung Depan/Belakang & Lot Termuda)")
st.caption("Algoritma hanya menyaring item yang berada di **ujung Belakang (Pallet Ke besar)** atau **ujung Depan (Pallet Ke = 1)** dengan prioritas utama di **Belakang** (agar tidak mengganggu akses Outbound) serta memiliki No. Lot tanggal produksi termuda/terbaru.")

saran_list = []

for r_loc, r_prof in rack_profiles.items():
    if r_prof['sku_cnt'] >= 3 and r_prof['pallets']:
        max_pallet = max(p['pallet_ke'] for p in r_prof['pallets'])
        
        # FILTER KUNCI: Hanya ambil item yang posisinya di Ujung Belakang (max_pallet) atau Ujung Depan (1)
        # Posisi tengah diabaikan agar tidak membongkar tumpukan.
        target_candidates = [p for p in r_prof['pallets'] if p['pallet_ke'] == max_pallet or p['pallet_ke'] == 1]
        
        if target_candidates:
            # Prioritas 1: Posisi di Belakang (Pallet Ke besar), Prioritas 2: Lot Tanggal Termuda (Terbaru)
            target_candidates = sorted(target_candidates, key=lambda x: (x['pallet_ke'] == max_pallet, x['lot_date']), reverse=True)
            target_pallet = target_candidates[0]
            
            pn_to_move = target_pallet['part_number']
            nama_item = target_pallet['name']
            lot_target = target_pallet['lot']
            pos_pallet = target_pallet['pallet_ke']
            
            # Tentukan label posisi untuk keterangan
             posisi_teks = "Ujung Belakang" if pos_pallet == max_pallet else "Ujung Depan"
            
            matching_pallets = [p for p in r_prof['pallets'] if p['part_number'] == pn_to_move]
            qty_to_move = len(matching_pallets)
            
            best_dest, best_score, alasan = None, -1, ""
            
            for d_loc, d_prof in rack_profiles.items():
                if r_loc == d_loc: continue
                
                if d_prof['usable'] >= qty_to_move and d_prof['sku_cnt'] < 2:
                    score = -1
                    dest_items_pn = [p['part_number'] for p in d_prof['pallets']]
                    
                    if d_prof['sku_cnt'] == 1 and pn_to_move in dest_items_pn: 
                        score, alasan_temp = 3, f"Digabung ke item sejenis di Rak Ideal | Diambil dari **{posisi_teks}** (#{pos_pallet}, Lot: {lot_target})"
                    elif d_prof['sku_cnt'] == 1 and pn_to_move not in dest_items_pn: 
                        score, alasan_temp = 2, f"Mengubah Rak Ideal jadi Campur | Diambil dari **{posisi_teks}** (#{pos_pallet}, Lot: {lot_target})"
                    elif d_prof['sku_cnt'] == 0: 
                        score, alasan_temp = 1, f"Dipindah ke Rak Kosong | Diambil dari **{posisi_teks}** (#{pos_pallet}, Lot: {lot_target})"
                    
                    if score > best_score:
                        best_score, best_dest, alasan = score, d_loc, alasan_temp
                        
            if best_dest:
                saran_list.append({
                    'Dari Rak (Asal)': f"{r_loc[0]}-{r_loc[1]}",
                    'Item & Lot Prioritas Pindah': f"{nama_item} (Lot: {lot_target})",
                    'Jumlah Pallet': f"{qty_to_move} Pallet",
                    'Ke Rak (Tujuan)': f"{best_dest[0]}-{best_dest[1]}",
                    'Analisis Dasar Relokasi': alasan,
                    'Skor': best_score
                })

if saran_list:
    seen_asal = set()
    unique_saran = []
    for s in sorted(saran_list, key=lambda x: x['Skor'], reverse=True):
        if s['Dari Rak (Asal)'] not in seen_asal:
            seen_asal.add(s['Dari Rak (Asal)'])
            unique_saran.append(s)
            
    df_saran = pd.DataFrame(unique_saran[:12]).drop(columns=['Skor'])
    st.dataframe(df_saran, use_container_width=True, hide_index=True)
else:
    st.success("🎉 Luar biasa! Saat ini tidak ada rak merah yang memenuhi kriteria relokasi dari ujung depan/belakang.")
