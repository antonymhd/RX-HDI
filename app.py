import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import re
import io
from datetime import datetime, timedelta
import plotly.express as px

# ==========================================================
# 1. KONFIGURASI HALAMAN
# ==========================================================
st.set_page_config(
    page_title="Warehouse 2D Racking", 
    page_icon="📦", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# ==========================================================
# 2. INIT FIREBASE (DATABASE UJI COBA)
# ==========================================================
NAMA_DATABASE = 'uji_coba_rak'

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ==========================================================
# 3. FUNGSI LOAD DATA (SMART CACHE & MASTER PRODUK)
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
            
    # Filter eksklusif hanya kolom Shuttle Racking (A - G)
    if 'Kolom' in df.columns:
        df['Kolom'] = df['Kolom'].astype(str).str.strip().str.upper()
        df = df[df['Kolom'].isin(['A', 'B', 'C', 'D', 'E', 'F', 'G'])].copy()
            
    return df

@st.cache_data(ttl=3600)
def load_master_produk():
    try:
        try: 
            df_master = pd.read_csv("Master_Produk.csv", sep=";", encoding='utf-8-sig')
        except: 
            df_master = pd.read_csv("Master_Produk.csv", sep=",", encoding='utf-8-sig')
        
        df_master.columns = df_master.columns.str.strip()
        if 'Part Number' in df_master.columns:
            df_master['Part Number Clean'] = df_master['Part Number'].astype(str).str.strip().str.upper()
        return df_master
    except:
        return pd.DataFrame()

# Optimasi RAM: Dictionary O(1) Lookup
df_master_global = load_master_produk()
master_dict = {}
if not df_master_global.empty and 'Part Number Clean' in df_master_global.columns:
    for _, row in df_master_global.iterrows():
        pn = row['Part Number Clean']
        ip = pd.to_numeric(row.get('Isi 1 Pallet (pcs)', 0), errors='coerce')
        pb = pd.to_numeric(row.get('Box / Pallet', 0), errors='coerce')
        ps = pd.to_numeric(row.get('Sac / Pallet', 0), errors='coerce')
        master_dict[pn] = {
            'ip': 0 if pd.isna(ip) else float(ip),
            'pb': 0 if pd.isna(pb) else float(pb),
            'ps': 0 if pd.isna(ps) else float(ps)
        }

# ==========================================================
# FUNGSI HELPER & GENERATOR KARTU RACKING
# ==========================================================
def get_waktu_jkt():
    return datetime.utcnow() + timedelta(hours=7)

def parse_lot_date(lot_str):
    cleaned = str(lot_str).strip()
    if len(cleaned) >= 6:
        date_str = cleaned[-6:]
        shift_char = cleaned[-7] if len(cleaned) >= 7 and cleaned[-7].isdigit() else '9'
        shift_num = int(shift_char)
        
        try:
            day = int(date_str[0:2])
            month = int(date_str[2:4])
            year = int('20' + date_str[4:6])
            return datetime(year, month, day, hour=shift_num)
        except:
            return datetime(2099, 12, 31, hour=23)
    return datetime(2099, 12, 31, hour=23)

def format_compact_number(num):
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M".replace('.0M', 'M')
    elif num >= 1_000:
        return f"{num/1_000:.1f}k".replace('.0k', 'k')
    return str(int(num))

def hitung_pcs_baris(row_ket, part_num):
    pn = str(part_num).strip().upper()
    ket_str = str(row_ket).lower()
    
    jml_utuh, val_pecahan, val_eceran = 0, 0, 0
    if 'pecahan' not in ket_str and 'eceran' not in ket_str:
        jml_utuh = 1
    else:
        mp = re.search(r'pecahan:\s*(\d+)', ket_str)
        if mp: 
            val_pecahan += int(mp.group(1))
        else:
            nums = re.findall(r'\d+', ket_str)
            if nums and 'pecahan' in ket_str: 
                val_pecahan += int(nums[0])
        me = re.search(r'eceran:\s*(\d+)', ket_str)
        if me: 
            val_eceran += int(me.group(1))
        
    master_info = master_dict.get(pn, {'ip': 0, 'pb': 0, 'ps': 0})
    pss = master_info['pb'] if pn.endswith(('D', 'G')) else master_info['ps']
    
    return (jml_utuh * master_info['ip']) + (val_pecahan * pss) + val_eceran

def build_picking_cards(kolom, baris, df_sub, prod_col):
    """
    Menyusun kartu racking: 1 kartu per Part Number (item sejenis).
    Di dalam 1 kartu bisa berisi beberapa baris Lot Number untuk item tersebut.
    """
    lokasi_str = f"{kolom}-{baris}"
    area_str = "Area 1 (1–16)" if baris <= 16 else "Area 2 (17–28)"
    
    if df_sub.empty or 'Part Number' not in df_sub.columns:
        return [{
            'Lokasi': lokasi_str, 'Area': area_str, 'Part Number': '-',
            'Nama Produk': 'RAK KOSONG', 'Total Fisik': '0', 'Total Pcs': 0,
            'Detail Lot': [], 'Is_Empty': True
        }]
        
    valid_df = df_sub[~df_sub['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan", "none", "<na>"])].copy()
    if valid_df.empty:
        return [{
            'Lokasi': lokasi_str, 'Area': area_str, 'Part Number': '-',
            'Nama Produk': 'RAK KOSONG', 'Total Fisik': '0', 'Total Pcs': 0,
            'Detail Lot': [], 'Is_Empty': True
        }]

    valid_df['PN_Clean'] = valid_df['Part Number'].astype(str).str.strip().str.upper()
    if 'Pallet Ke' in valid_df.columns:
        valid_df = valid_df.sort_values(by='Pallet Ke', ascending=True)

    # Urutkan kemunculan Part Number berdasarkan posisi terdepan (Pallet Ke terkecil)
    pn_order = valid_df.groupby('PN_Clean')['Pallet Ke'].min().sort_values().index.tolist()
    cards = []

    for pn in pn_order:
        df_item = valid_df[valid_df['PN_Clean'] == pn].copy()
        prod_name = str(df_item[prod_col].dropna().values[0]).strip() if prod_col in df_item.columns and len(df_item[prod_col].dropna().values) > 0 else "-"
        
        master_info = master_dict.get(pn, {'ip': 0, 'pb': 0, 'ps': 0})
        pss = master_info['pb'] if pn.endswith(('D', 'G')) else master_info['ps']
        satuan_pecahan = "Dus" if pn.endswith(('D', 'G')) else "Sak"

        df_item['Lot_Clean'] = df_item['Lot Number'].fillna('-').astype(str).str.strip()
        df_item['Tgl_Sort'] = df_item['Lot_Clean'].apply(parse_lot_date)
        df_item = df_item.sort_values(by=['Tgl_Sort', 'Pallet Ke'], ascending=[True, True])

        lot_details = []
        tot_item_utuh, tot_item_pecahan, tot_item_eceran, tot_item_pcs = 0, 0, 0, 0

        for lot_val, grp_lot in df_item.groupby('Lot_Clean', sort=False):
            pallets = sorted(grp_lot['Pallet Ke'].tolist())
            plt_range = f"{pallets[0]}–{pallets[-1]}" if len(pallets) > 1 else str(pallets[0])
            
            u, p_val, e_val = 0, 0, 0
            catatan_set = set()
            for _, r in grp_lot.iterrows():
                ket_str = str(r.get('Keterangan', '')).lower()
                if 'pecahan' not in ket_str and 'eceran' not in ket_str:
                    u += 1
                else:
                    mp = re.search(r'pecahan:\s*(\d+)', ket_str)
                    if mp:
                        p_val += int(mp.group(1))
                    else:
                        nums = re.findall(r'\d+', ket_str)
                        if nums and 'pecahan' in ket_str:
                            p_val += int(nums[0])
                    me = re.search(r'eceran:\s*(\d+)', ket_str)
                    if me:
                        e_val += int(me.group(1))
                
                cat_str = str(r.get('Catatan', '')).strip()
                if cat_str and cat_str.lower() not in ['nan', 'none', '']:
                    catatan_set.add(cat_str)

            pcs_lot = (u * master_info['ip']) + (p_val * pss) + e_val
            tot_item_utuh += u
            tot_item_pecahan += p_val
            tot_item_eceran += e_val
            tot_item_pcs += pcs_lot

            qty_parts = []
            if u > 0: qty_parts.append(f"{u} Plt")
            if p_val > 0: qty_parts.append(f"{p_val} {satuan_pecahan}")
            if e_val > 0: qty_parts.append(f"{e_val} Pcs")
            qty_str = " + ".join(qty_parts) if qty_parts else "0"

            tgl_dt = parse_lot_date(lot_val)
            tgl_str = tgl_dt.strftime('%d-%m-%Y') if tgl_dt.year != 2099 else "-"

            lot_details.append({
                'lot': lot_val,
                'tgl': tgl_str,
                'pallet_range': plt_range,
                'qty_str': qty_str,
                'pcs': int(pcs_lot),
                'catatan': ", ".join(sorted(catatan_set)) if catatan_set else "-"
            })

        tot_parts = []
        if tot_item_utuh > 0: tot_parts.append(f"{tot_item_utuh} Plt")
        if tot_item_pecahan > 0: tot_parts.append(f"{tot_item_pecahan} {satuan_pecahan}")
        if tot_item_eceran > 0: tot_parts.append(f"{tot_item_eceran} Pcs")

        cards.append({
            'Lokasi': lokasi_str,
            'Area': area_str,
            'Part Number': pn,
            'Nama Produk': prod_name,
            'Total Fisik': " + ".join(tot_parts) if tot_parts else "0",
            'Total Pcs': int(tot_item_pcs),
            'Detail Lot': lot_details,
            'Is_Empty': False
        })

    return cards

def render_print_html(cards, judul_dok, waktu_cetak):
    """Merender kartu racking HTML siap cetak (2 kartu per baris A4, anti-terpotong)."""
    cards_html = ""
    for c in cards:
        if c['Is_Empty']:
            cards_html += f"""
            <div class="card empty-card">
                <div class="card-header">
                    <div class="loc-badge">{c['Lokasi']}</div>
                    <div class="area-tag">{c['Area']}</div>
                </div>
                <div class="empty-body">
                    <div class="empty-title">RAK KOSONG</div>
                    <div class="empty-sub">Siap diisi inbound</div>
                </div>
                <div class="card-footer">
                    <span>Dicetak: {waktu_cetak}</span>
                    <span>Paraf: ___________</span>
                </div>
            </div>
            """
        else:
            rows_html = ""
            for idx, ld in enumerate(c['Detail Lot'], start=1):
                pcs_fmt = f"{ld['pcs']:,.0f}".replace(',', '.') if ld['pcs'] > 0 else "-"
                cat_badge = f"<br><span class='cat-warn'>{ld['catatan']}</span>" if ld['catatan'] != "-" else ""
                rows_html += f"""
                <tr>
                    <td class="center">{idx}</td>
                    <td class="bold">{ld['lot']}{cat_badge}</td>
                    <td class="center">{ld['tgl']}</td>
                    <td class="center bold">{ld['pallet_range']}</td>
                    <td class="right">{ld['qty_str']}</td>
                    <td class="right bold">{pcs_fmt}</td>
                </tr>
                """
            tot_pcs_fmt = f"{c['Total Pcs']:,.0f}".replace(',', '.')
            cards_html += f"""
            <div class="card">
                <div class="card-header">
                    <div class="loc-badge">{c['Lokasi']}</div>
                    <div class="prod-box">
                        <div class="pn-text">{c['Part Number']}</div>
                        <div class="prod-name">{c['Nama Produk']}</div>
                    </div>
                </div>
                <table class="lot-table">
                    <thead>
                        <tr>
                            <th style="width:6%;">#</th>
                            <th style="width:26%;">Lot Number</th>
                            <th style="width:18%;">Tgl Prod</th>
                            <th style="width:14%;">Plt Ke</th>
                            <th style="width:18%;">Qty Fisik</th>
                            <th style="width:18%;">Total Pcs</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                    <tfoot>
                        <tr>
                            <td colspan="4" class="right bold">TOTAL ITEM DI RAK INI:</td>
                            <td class="right bold">{c['Total Fisik']}</td>
                            <td class="right bold total-pcs">{tot_pcs_fmt} Pcs</td>
                        </tr>
                    </tfoot>
                </table>
                <div class="card-footer">
                    <span>{c['Area']} | {waktu_cetak}</span>
                    <span>Operator: ______________</span>
                </div>
            </div>
            """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            margin: 0;
            padding: 12px;
            background: #f1f5f9;
            color: #0f172a;
        }}
        .toolbar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #1e293b;
            color: white;
            padding: 10px 16px;
            border-radius: 8px;
            margin-bottom: 14px;
        }}
        .toolbar-title {{
            font-size: 14px;
            font-weight: 700;
        }}
        .print-btn {{
            background: #2563eb;
            color: white;
            border: none;
            padding: 8px 18px;
            font-size: 14px;
            font-weight: 700;
            border-radius: 6px;
            cursor: pointer;
        }}
        .print-btn:hover {{ background: #1d4ed8; }}
        .grid-cards {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
        }}
        .card {{
            background: white;
            border: 2px solid #0f172a;
            border-radius: 6px;
            padding: 10px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            page-break-inside: avoid;
            break-inside: avoid;
        }}
        .empty-card {{
            border: 2px dashed #94a3b8;
            background: #f8fafc;
        }}
        .card-header {{
            display: flex;
            align-items: center;
            gap: 10px;
            border-bottom: 2px solid #0f172a;
            padding-bottom: 8px;
            margin-bottom: 8px;
        }}
        .loc-badge {{
            background: #0f172a;
            color: white;
            font-size: 22px;
            font-weight: 900;
            padding: 6px 12px;
            border-radius: 4px;
            min-width: 64px;
            text-align: center;
            letter-spacing: 0.5px;
        }}
        .prod-box {{
            flex: 1;
            overflow: hidden;
        }}
        .pn-text {{
            font-size: 13px;
            font-weight: 800;
            color: #1d4ed8;
        }}
        .prod-name {{
            font-size: 13px;
            font-weight: 700;
            color: #0f172a;
            line-height: 1.25;
        }}
        .area-tag {{
            font-size: 12px;
            font-weight: 700;
            color: #475569;
        }}
        .lot-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
            margin-bottom: 8px;
        }}
        .lot-table th, .lot-table td {{
            border: 1px solid #cbd5e1;
            padding: 4px 5px;
        }}
        .lot-table th {{
            background: #e2e8f0;
            font-weight: 800;
            text-align: center;
        }}
        .lot-table tfoot td {{
            background: #f8fafc;
            border-top: 2px solid #0f172a;
            font-size: 11.5px;
        }}
        .total-pcs {{ color: #1d4ed8; }}
        .cat-warn {{
            font-size: 9.5px;
            color: #b91c1c;
            font-weight: 700;
        }}
        .center {{ text-align: center; }}
        .right {{ text-align: right; }}
        .bold {{ font-weight: 700; }}
        .empty-body {{
            text-align: center;
            padding: 24px 0;
            color: #64748b;
        }}
        .empty-title {{ font-size: 18px; font-weight: 900; }}
        .empty-sub {{ font-size: 12px; }}
        .card-footer {{
            display: flex;
            justify-content: space-between;
            font-size: 10.5px;
            color: #475569;
            border-top: 1px solid #cbd5e1;
            padding-top: 5px;
        }}
        @media print {{
            body {{ background: white; padding: 0; }}
            .toolbar {{ display: none !important; }}
            .grid-cards {{ gap: 8px; }}
        }}
    </style>
    </head>
    <body>
        <div class="toolbar">
            <div class="toolbar-title">🖨️ {judul_dok} ({len(cards)} Kartu)</div>
            <button class="print-btn" onclick="window.print()">🖨️ Cetak Kartu Sekarang</button>
        </div>
        <div class="grid-cards">
            {cards_html}
        </div>
    </body>
    </html>
    """

# ==========================================================
# 4. SIDEBAR & PENGATURAN
# ==========================================================
st.sidebar.header("🔄 Sinkronisasi Real-Time")
st.sidebar.info("Data dikunci selama 5 menit untuk menghemat kuota Firebase.")

if st.sidebar.button("🔄 Tarik Data Gudang Terbaru", use_container_width=True, type="primary"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.header("👁️ Mode Tampilan Kotak")
mode_tampilan = st.sidebar.radio("Angka di dalam kotak rak mewakili:", [
    "Variasi SKU (Jenis Barang)", 
    "Sisa Slot Kosong"
])

# ==========================================================
# 5. MEMUAT DATA UTAMA & PENCARIAN
# ==========================================================
st.title("📦 Visualisasi Grid Gudang (Live Monitor)")
st.caption(f"Layar pantau Read-Only. Terhubung ke database: {NAMA_DATABASE} (Area Shuttle A - G)")

df = load_data_from_firebase()

if df.empty or 'Kolom' not in df.columns:
    st.warning("Gudang kosong atau aplikasi sedang sinkronisasi. Harap tunggu...")
    st.stop()

product_col = 'Nama Produk' if 'Nama Produk' in df.columns else 'Nama Barang'

st.sidebar.header("🔍 Pencarian Spesifik")
tipe_cari = st.sidebar.radio("Metode Pencarian:", ["Berdasarkan Produk", "Berdasarkan Part Number", "Berdasarkan No. Lot"])
search_query, search_lot = "", ""

if tipe_cari in ["Berdasarkan Produk", "Berdasarkan Part Number"]:
    search_col = product_col if tipe_cari == "Berdasarkan Produk" else 'Part Number'
    
    if search_col in df.columns:
        valid_mask = ~df[search_col].astype(str).str.strip().str.lower().isin(["", "nan", "none", "<na>"])
        daftar_pilihan = sorted(df[valid_mask][search_col].dropna().astype(str).unique().tolist())
    else: 
        daftar_pilihan = []
        
    label_selectbox = "Pilih Produk:" if tipe_cari == "Berdasarkan Produk" else "Pilih Part Number:"
    pilihan_pencarian = st.sidebar.selectbox(label_selectbox, options=["-- Tampilkan Semua --"] + daftar_pilihan)
    search_query = "" if pilihan_pencarian == "-- Tampilkan Semua --" else pilihan_pencarian
    
    if search_query:
        st.markdown(f"### 🔎 Lokasi Pengambilan **{search_query}** (Urutan FIFO)")
        
        q_clean = search_query.strip().lower()
        df_search = df[
            (df[search_col].astype(str).str.strip().str.lower() == q_clean) &
            (df['Kolom'].isin(['A', 'B', 'C', 'D', 'E', 'F', 'G']))
        ].copy()
        
        if not df_search.empty:
            df_search['Tgl_Produksi'] = df_search['Lot Number'].apply(parse_lot_date)
            df_search = df_search.sort_values(by=['Tgl_Produksi', 'Kolom', 'Baris', 'Pallet Ke'], ascending=[True, True, True, True])
            
            fifo_summary = []
            grouped = df_search.groupby(['Kolom', 'Baris', 'Part Number', 'Lot Number', 'Tgl_Produksi'], dropna=False)
            
            grand_total_search_pcs = 0 
            
            for name, group in grouped:
                kolom, baris, part_num, lot, tgl = name
                pallets = sorted(group['Pallet Ke'].tolist())
                pallet_range = f"{pallets[0]} - {pallets[-1]}" if len(pallets) > 1 else str(pallets[0]) if pallets else "-"
                
                pn_clean = str(part_num).strip().upper()
                master_info = master_dict.get(pn_clean, {'ip': 0, 'pb': 0, 'ps': 0})
                pss = master_info['pb'] if pn_clean.endswith(('D', 'G')) else master_info['ps']
                
                jml_utuh, val_pecahan, val_eceran = 0, 0, 0
                for _, row in group.iterrows():
                    ket_str = str(row.get('Keterangan', '')).lower()
                    if 'pecahan' not in ket_str and 'eceran' not in ket_str: 
                        jml_utuh += 1
                    else:
                        mp = re.search(r'pecahan:\s*(\d+)', ket_str)
                        if mp: 
                            val_pecahan += int(mp.group(1))
                        else:
                            nums = re.findall(r'\d+', ket_str)
                            if nums and 'pecahan' in ket_str: 
                                val_pecahan += int(nums[0])
                        me = re.search(r'eceran:\s*(\d+)', ket_str)
                        if me: 
                            val_eceran += int(me.group(1))
                
                total_pcs_group = (jml_utuh * master_info['ip']) + (val_pecahan * pss) + val_eceran
                grand_total_search_pcs += total_pcs_group
                
                stok_str = []
                if jml_utuh > 0: stok_str.append(f"{jml_utuh} Plt")
                if val_pecahan > 0: stok_str.append(f"{val_pecahan} Dus/Sak")
                if val_eceran > 0: stok_str.append(f"{val_eceran} Pcs")
                
                fisik_str = " + ".join(stok_str) if stok_str else "0"
                
                if master_info['ip'] > 0 or total_pcs_group > 0:
                    pcs_format = f"{total_pcs_group:,.0f}".replace(',', '.')
                    fisik_str += f" ➔ {pcs_format} Pcs"
                
                fifo_summary.append({
                    'Lokasi Rak': f"{kolom}-{baris}",
                    'Part Number': part_num,
                    'Lot Number': lot,
                    'Jumlah Stok (Fisik & Pcs)': fisik_str,
                    'Range Pallet Ke': pallet_range,
                    'Tanggal Produksi': tgl,
                    'Urutan_Sort': tgl
                })
                
            df_fifo = pd.DataFrame(fifo_summary).sort_values('Urutan_Sort').drop(columns=['Urutan_Sort'])
            df_fifo['Tanggal Produksi'] = df_fifo['Tanggal Produksi'].apply(lambda x: x.strftime('%d-%m-%Y') if x.year != 2099 else "Strip/Tidak Valid")
            df_fifo = df_fifo[['Lokasi Rak', 'Part Number', 'Lot Number', 'Jumlah Stok (Fisik & Pcs)', 'Range Pallet Ke', 'Tanggal Produksi']]
            
            st.info(f"💡 **Rekomendasi Ambil Pertama (Paling Lama):** Rak **{df_fifo.iloc[0]['Lokasi Rak']}** (Lot: {df_fifo.iloc[0]['Lot Number']}) dengan {df_fifo.iloc[0]['Jumlah Stok (Fisik & Pcs)']}")
            st.dataframe(df_fifo, use_container_width=True, hide_index=True)
            
            if grand_total_search_pcs > 0:
                total_semua_format = f"{grand_total_search_pcs:,.0f}".replace(',', '.')
                st.markdown(
                    f"<div style='text-align: right; padding-top: 8px; font-size: 16px; color: #475569;'>"
                    f"Total Kuantitas Keseluruhan (Rak A-G): <span style='color: #2563eb; font-weight: 900; font-size: 18px;'>{total_semua_format} Pcs</span>"
                    f"</div>", 
                    unsafe_allow_html=True
                )
            st.divider()
        else:
            st.warning("Data tidak ditemukan di rak A-G.")
else:
    if 'Lot Number' in df.columns:
        valid_mask = ~df['Lot Number'].astype(str).str.strip().str.lower().isin(["", "nan", "none", "<na>", "-", "0"])
        daftar_lot = sorted(df[valid_mask]['Lot Number'].dropna().astype(str).unique().tolist())
    else: 
        daftar_lot = []
        
    pilihan_lot = st.sidebar.selectbox("Pilih No. Lot:", options=["-- Tampilkan Semua --"] + daftar_lot)
    search_lot = "" if pilihan_lot == "-- Tampilkan Semua --" else pilihan_lot

# ==========================================================
# 6. LOGIKA MATRIKS RAK (CACHED UNTUK POP-UP INSTAN)
# ==========================================================
def is_rack_exist(kolom, baris):
    if kolom == 'F' and baris < 5: return False
    if kolom == 'G' and baris < 17: return False
    return True

@st.cache_data(ttl=300)
def process_matrix_data(df, search_term, search_lot_term, prod_col):
    kolom_list = ['G', 'F', 'E', 'D', 'C', 'B', 'A']
    baris_list = list(range(1, 29))
    matrix_info = {}
    
    total_critical, total_warning, total_ideal, total_kosong = 0, 0, 0, 0
    total_slot_ideal, total_slot_warning = 0, 0
    
    term_clean = search_term.strip().lower() if search_term else ""
    lot_term_clean = search_lot_term.strip().lower() if search_lot_term else ""

    grouped_racks = dict(tuple(df.groupby(['Kolom', 'Baris'])))

    for k in kolom_list:
        for b in baris_list:
            if not is_rack_exist(k, b):
                matrix_info[(k, b)] = {'exist': False}
                continue
                
            sub = grouped_racks.get((k, b), pd.DataFrame(columns=df.columns))
            is_all_box, filled, sku, is_match = False, 0, 0, False
            
            if 'Part Number' in sub.columns and not sub.empty:
                p_series = sub['Part Number'].astype(str).str.strip()
                valid_mask = ~p_series.str.lower().isin(["", "nan", "none", "<na>"])
                p_valid = p_series[valid_mask]
                
                filled = int(valid_mask.sum())
                sku = len(p_valid.unique())
                
                if not p_valid.empty:
                    is_all_box = bool(p_valid.str.upper().str.endswith(('D', 'G')).all())
                    
                if term_clean:
                    m_part = (p_series.str.lower() == term_clean).any()
                    m_prod = (sub[prod_col].astype(str).str.strip().str.lower() == term_clean).any() if prod_col in sub.columns else False
                    is_match = bool(m_part or m_prod)
                elif lot_term_clean:
                    if 'Lot Number' in sub.columns:
                        is_match = (sub['Lot Number'].astype(str).str.strip().str.lower() == lot_term_clean).any()
                        
            max_slot = int(32 if b <= 16 else 46) if is_all_box else int(31 if b <= 16 else 44)
            usable_space = max(0, max_slot - filled)
            
            if sku >= 3: 
                total_critical += 1
            elif sku == 2: 
                total_warning += 1
                if usable_space > 1: total_slot_warning += usable_space
            elif sku == 1:
                total_ideal += 1
                if usable_space > 1: total_slot_ideal += usable_space
            elif sku == 0: 
                total_kosong += 1
                
            matrix_info[(k, b)] = {
                'exist': True, 'sku_cnt': sku, 'filled': filled, 
                'usable_space': usable_space, 'max_slot': max_slot, 
                'df_sub': sub, 'is_match': is_match
            }
            
    return matrix_info, total_critical, total_warning, total_ideal, total_kosong, total_slot_ideal, total_slot_warning, kolom_list, baris_list

matrix_info, total_critical, total_warning, total_ideal, total_kosong, total_slot_ideal, total_slot_warning, kolom_list, baris_list = process_matrix_data(df, search_query, search_lot, product_col)

# ----------------------------------------------------------
# FITUR PANTAU RAK OVERLIMIT / ABNORMAL (BAYANGAN)
# ----------------------------------------------------------
st.sidebar.divider()
st.sidebar.header("🚨 Peringatan Rak Overlimit")
st.sidebar.caption("Memantau rak yang jumlah fisiknya melebihi kapasitas.")

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
    st.sidebar.error(f"⚠️ **Ditemukan {len(rak_bermasalah)} Rak Overlimit:**\n\n{', '.join(sorted(list(rak_bermasalah)))}")
    df_bayangan = pd.DataFrame(bayangan_data)
    cols_tersedia = [c for c in ['Kolom', 'Baris', 'Pallet Ke', 'Part Number', product_col, 'Lot Number', 'Keterangan', 'Catatan'] if c in df_bayangan.columns]
    df_bayangan = df_bayangan[cols_tersedia].sort_values(by=['Kolom', 'Baris', 'Pallet Ke'])
    csv = df_bayangan.to_csv(index=False, sep=";").encode('utf-8-sig')
    st.sidebar.download_button(
        label="📥 Unduh Daftar Pallet Bayangan", 
        data=csv, 
        file_name=f"Cek_Lapangan_Overlimit_{get_waktu_jkt().strftime('%Y%m%d_%H%M')}.csv", 
        mime="text/csv", 
        type="primary"
    )
else:
    st.sidebar.success("✅ Seluruh rak dalam batas kapasitas normal.")

# ==========================================================
# 7. POP-UP DETAIL RAK (+ CETAK KARTU CEPAT)
# ==========================================================
@st.dialog("📦 Rincian Detail Rak", width="large")
def show_rack_detail(k, b, info):
    grand_total_pcs = 0
    if info['sku_cnt'] > 0:
        df_terisi_awal = info['df_sub'][~info['df_sub']['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan", "none", "<na>"])]
        for _, row in df_terisi_awal.iterrows():
            grand_total_pcs += hitung_pcs_baris(row.get('Keterangan', ''), row.get('Part Number', ''))

    st.subheader(f"📍 Lokasi Racking: {k} - Baris {b}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Variasi SKU", f"{info['sku_cnt']} Jenis")
    c2.metric("Slot Fisik Terpakai", f"{info['filled']} / {info['max_slot']}")
    c3.metric("Space Kosong", f"{info['usable_space']} Slot")
    c4.metric("Total Kuantitas", format_compact_number(grand_total_pcs) + " Pcs")
    st.divider()
    
    if info['sku_cnt'] > 0:
        df_terisi = info['df_sub'][~info['df_sub']['Part Number'].astype(str).str.strip().str.lower().isin(["", "nan", "none", "<na>"])]
        
        rekap_data = []
        for part_num in df_terisi['Part Number'].astype(str).str.strip().unique():
            df_prod = df_terisi[df_terisi['Part Number'].astype(str).str.strip() == part_num]
            prod_name = str(df_prod[product_col].dropna().values[0]) if product_col in df_prod.columns and len(df_prod[product_col].dropna().values) > 0 else "-"
            
            pnc = str(part_num).strip().upper() 
            master_info = master_dict.get(pnc, {'ip': 0, 'pb': 0, 'ps': 0})
            
            jml_utuh, val_pecahan, val_eceran = 0, 0, 0
            for _, row in df_prod.iterrows():
                ket_str = str(row.get('Keterangan', '')).lower()
                if 'pecahan' not in ket_str and 'eceran' not in ket_str: 
                    jml_utuh += 1
                else:
                    mp = re.search(r'pecahan:\s*(\d+)', ket_str)
                    if mp: 
                        val_pecahan += int(mp.group(1))
                    else:
                        nums = re.findall(r'\d+', ket_str)
                        if nums and 'pecahan' in ket_str: 
                            val_pecahan += int(nums[0])
                    me = re.search(r'eceran:\s*(\d+)', ket_str)
                    if me: 
                        val_eceran += int(me.group(1))

            sc = "Dus" if pnc.endswith(('D', 'G')) else "Sak"
            pss = master_info['pb'] if pnc.endswith(('D', 'G')) else master_info['ps']
            
            if master_info['ip'] > 0:
                tot = (jml_utuh * master_info['ip']) + (val_pecahan * pss) + val_eceran
                teks_rincian = f"{jml_utuh} Pallet * {master_info['ip']:,.0f}"
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
        avail = [c for c in ['Pallet Ke', 'Part Number', 'Lot Number', product_col, 'Keterangan', 'Catatan'] if c in df_terisi.columns]
        df_tampil = df_terisi[avail].copy()
        if 'Pallet Ke' in df_tampil.columns: 
            df_tampil = df_tampil.sort_values(by='Pallet Ke', ascending=True)
            
        def highlight_bayangan(row):
            cat = str(row.get('Catatan', '')).upper()
            if 'BAYANGAN' in cat: return ['background-color: #fef2f2; color: #991b1b; font-weight: bold;'] * len(row)
            elif 'BOOKED' in cat: return ['background-color: #eff6ff; color: #1e3a8a; font-weight: bold; border-left: 4px solid #2563eb;'] * len(row)
            return [''] * len(row)
            
        st.dataframe(df_tampil.style.apply(highlight_bayangan, axis=1), use_container_width=True, hide_index=True)
    else:
        st.success("✅ Rak Kosong. Aman untuk diisi.")

    # Pratinjau & Cetak Kartu Racking langsung untuk lokasi ini
    st.divider()
    with st.expander(f"🖨️ Cetak Kartu Racking Rak {k}-{b} ({max(1, info['sku_cnt'])} Kartu)"):
        kartu_single = build_picking_cards(k, b, info['df_sub'], product_col)
        html_single = render_print_html(kartu_single, f"Kartu Racking {k}-{b}", get_waktu_jkt().strftime("%d-%m-%Y %H:%M WIB"))
        components.html(html_single, height=380, scrolling=True)

# ==========================================================
# 8. RENDER METRIK, CHART, & GRID UI
# ==========================================================
col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
total_baris_hitung = total_ideal + total_warning + total_critical + total_kosong

col_m1.metric("Total Baris Aktif", f"{total_baris_hitung} Baris")
col_m2.metric("🟢 Rak Ideal (1 SKU)", f"{total_ideal} Baris", f"{total_slot_ideal} Slot Siap Isi", delta_color="normal")
col_m3.metric("🟡 Rak Campur (2 SKU)", f"{total_warning} Baris", f"{total_slot_warning} Slot Siap Isi", delta_color="normal")
col_m4.metric("🔴 Rak Kritis (>= 3 SKU)", f"{total_critical} Baris", "Hindari Inbound", delta_color="off")
col_m5.metric("⚪ Rak Kosong Bersih", f"{total_kosong} Baris")

# --- DONUT CHART ---
st.write("")
col_chart1, col_chart2, col_chart3 = st.columns([1, 2, 1])
with col_chart2:
    df_pie = pd.DataFrame({
        'Status': ['🟢 Ideal', '🟡 Campur', '🔴 Kritis', '⚪ Kosong'],
        'Jumlah': [total_ideal, total_warning, total_critical, total_kosong]
    })
    
    warna_pie = {
        '🟢 Ideal': 'palegreen', 
        '🟡 Campur': 'gold', 
        '🔴 Kritis': 'crimson', 
        '⚪ Kosong': 'gainsboro'
    }

    fig = px.pie(
        df_pie, 
        values='Jumlah', 
        names='Status', 
        color='Status',
        color_discrete_map=warna_pie, 
        hole=0.4
    )
    
    fig.update_traces(
        textposition='inside', 
        textinfo='percent+label',
        hovertemplate="<b>%{label}</b><br>Jumlah: %{value} Rak<br>Persentase: %{percent}<extra></extra>",
        textfont_size=14, 
        textfont_color='black'
    )
    
    fig.update_layout(
        margin=dict(t=20, b=20, l=0, r=0), 
        height=280, 
        showlegend=False,
        plot_bgcolor='rgba(0,0,0,0)', 
        paper_bgcolor='rgba(0,0,0,0)'
    )

    st.plotly_chart(fig, use_container_width=True)

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
        with header_cols[idx + 1]: 
            st.markdown(f"<div style='text-align:center; font-weight:900; font-size:14px; color:#94a3b8; margin-bottom:4px;'>{b}</div>", unsafe_allow_html=True)
    
    for k in kolom_list:
        cols = st.columns([0.6] + [1] * 16, gap="small")
        with cols[0]: st.markdown(f"<div style='font-weight:900;'>{k}</div>", unsafe_allow_html=True)
            
        for idx, b in enumerate(list(range(start_baris, end_baris + 1))):
            info = matrix_info[(k, b)]
            with cols[idx + 1]:
                if info['exist']:
                    lbl = str(info['usable_space']) if mode_tampilan == "Sisa Slot Kosong" else str(info['sku_cnt'])
                    if st.button(lbl, key=f"btn_{k}_{b}", use_container_width=True): 
                        show_rack_detail(k, b, info)

render_grid_area("📍 Area 1 (Rak 1 - 16)", 1, 16)
st.divider()
render_grid_area("📍 Area 2 (Rak 17 - 28)", 17, 28)

# ==========================================================
# 9. DAFTAR LOKASI RAK & STATUS BLOK
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

list_merah, list_kuning, list_hijau, list_abu = [], [], [], []

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

# ==========================================================
# 10. CETAK KARTU RACKING / PICKING LIST (1 KARTU PER ITEM)
# ==========================================================
st.divider()
st.markdown("### 🖨️ Cetak Kartu Racking / Petunjuk Pengambilan (A-1 s/d G-28)")
st.caption("0 Kuota Firebase tambahan: kartu disusun langsung dari cache memori aktif. 1 kartu mewakili 1 Part Number (memuat seluruh Lot sejenis di rak tersebut).")

KOLOM_URUT_AG = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
daftar_semua_lokasi = [
    f"{k}-{b}"
    for b in range(1, 29)
    for k in KOLOM_URUT_AG
    if is_rack_exist(k, b)
]

mode_cetak = st.radio(
    "Pilih Mode Cetak:",
    ["🎯 Lokasi Spesifik (Pilih / Ketik Bebas)", "📑 Rentang Massal (Per Kolom & Baris)"],
    horizontal=True,
    key="print_mode_radio"
)

target_lokasi_list = []

if mode_cetak.startswith("🎯"):
    sp_c1, sp_c2 = st.columns([2, 1])
    with sp_c1:
        pilih_lokasi_multi = st.multiselect(
            "Pilih Satu atau Beberapa Lokasi Rak:",
            options=daftar_semua_lokasi,
            placeholder="Contoh: A-1, B-2, E-14...",
            key="print_multi_loc"
        )
    with sp_c2:
        ketik_lokasi_manual = st.text_input(
            "Atau Ketik Cepat (pisah koma/spasi):",
            placeholder="Cth: A-1, 5C, E-14",
            key="print_manual_loc"
        )

    seen_loc = set()
    for loc in pilih_lokasi_multi:
        if loc not in seen_loc:
            target_lokasi_list.append(loc)
            seen_loc.add(loc)

    if ketik_lokasi_manual and ketik_lokasi_manual.strip():
        tokens = re.split(r'[\s,;]+', ketik_lokasi_manual.strip().upper())
        for tok in tokens:
            if not tok:
                continue
            m1 = re.fullmatch(r'([A-G])-?(\d{1,2})', tok)
            m2 = re.fullmatch(r'(\d{1,2})-?([A-G])', tok)
            k_parsed, b_parsed = None, None
            if m1:
                k_parsed, b_parsed = m1.group(1), int(m1.group(2))
            elif m2:
                b_parsed, k_parsed = int(m2.group(1)), m2.group(2)

            if k_parsed and b_parsed and 1 <= b_parsed <= 28 and is_rack_exist(k_parsed, b_parsed):
                norm_loc = f"{k_parsed}-{b_parsed}"
                if norm_loc not in seen_loc:
                    target_lokasi_list.append(norm_loc)
                    seen_loc.add(norm_loc)
            else:
                st.warning(f"⚠️ Lokasi '{tok}' tidak valid atau tidak tersedia secara fisik (cek batas F5-F28 & G17-G28).")
else:
    p_col1, p_col2, p_col3, p_col4 = st.columns([2, 1, 1, 2])
    with p_col1:
        pilih_kolom_cetak = st.multiselect(
            "Pilih Kolom Racking",
            options=KOLOM_URUT_AG,
            default=KOLOM_URUT_AG,
            key="print_kolom_sel"
        )
    with p_col2:
        baris_awal_cetak = st.number_input("Dari Baris", min_value=1, max_value=28, value=1, key="print_b_start")
    with p_col3:
        baris_akhir_cetak = st.number_input("Sampai Baris", min_value=1, max_value=28, value=28, key="print_b_end")
    with p_col4:
        mode_urutan = st.selectbox(
            "Urutan Cetak",
            ["Per Baris (A-1, B-1 ... G-28)", "Per Kolom (A-1, A-2 ... G-28)"],
            key="print_sort_mode"
        )

    if pilih_kolom_cetak and baris_awal_cetak <= baris_akhir_cetak:
        kolom_terurut = [k for k in KOLOM_URUT_AG if k in pilih_kolom_cetak]
        rentang_baris = range(int(baris_awal_cetak), int(baris_akhir_cetak) + 1)
        if mode_urutan.startswith("Per Baris"):
            target_lokasi_list = [f"{k}-{b}" for b in rentang_baris for k in kolom_terurut if is_rack_exist(k, b)]
        else:
            target_lokasi_list = [f"{k}-{b}" for k in kolom_terurut for b in rentang_baris if is_rack_exist(k, b)]
    elif baris_awal_cetak > baris_akhir_cetak:
        st.error("❌ 'Dari Baris' tidak boleh lebih besar dari 'Sampai Baris'.")

sertakan_kosong = st.checkbox("Sertakan kartu untuk rak kosong", value=False, key="print_include_empty")

if target_lokasi_list:
    semua_kartu = []
    for loc in target_lokasi_list:
        k_id, b_str = loc.split('-')
        b_num = int(b_str)
        info_rak = matrix_info.get((k_id, b_num), {})
        if info_rak.get('exist'):
            kartu_rak = build_picking_cards(k_id, b_num, info_rak['df_sub'], product_col)
            for krt in kartu_rak:
                if krt['Is_Empty'] and not sertakan_kosong:
                    continue
                semua_kartu.append(krt)

    if semua_kartu:
        info_c1, info_c2 = st.columns([2, 1])
        with info_c1:
            jml_isi = sum(1 for c in semua_kartu if not c['Is_Empty'])
            jml_kosong = sum(1 for c in semua_kartu if c['Is_Empty'])
            st.success(f"✅ Siap Cetak: **{len(semua_kartu)} Kartu Item** dari **{len(target_lokasi_list)} Lokasi** ({jml_isi} Kartu Terisi, {jml_kosong} Kartu Kosong).")
        with info_c2:
            csv_rows = []
            for c in semua_kartu:
                if c['Is_Empty']:
                    csv_rows.append({
                        'Lokasi': c['Lokasi'], 'Part Number': '-', 'Nama Produk': 'RAK KOSONG',
                        'Lot Number': '-', 'Range Pallet Ke': '-', 'Qty Fisik': '0', 'Total Pcs': 0
                    })
                else:
                    for ld in c['Detail Lot']:
                        csv_rows.append({
                            'Lokasi': c['Lokasi'], 'Part Number': c['Part Number'], 'Nama Produk': c['Nama Produk'],
                            'Lot Number': ld['lot'], 'Range Pallet Ke': ld['pallet_range'],
                            'Qty Fisik': ld['qty_str'], 'Total Pcs': ld['pcs']
                        })
            df_print_csv = pd.DataFrame(csv_rows)
            csv_print_buf = io.StringIO()
            df_print_csv.to_csv(csv_print_buf, index=False, sep=";")
            st.download_button(
                label="⬇️ Unduh Data Kartu (CSV)",
                data=csv_print_buf.getvalue(),
                file_name=f"Kartu_Racking_{get_waktu_jkt().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True
            )

        ringkasan_judul = ", ".join(target_lokasi_list[:6]) + (f" (+{len(target_lokasi_list)-6} lainnya)" if len(target_lokasi_list) > 6 else "")
        judul_dok = f"Kartu Racking: {ringkasan_judul}"
        waktu_skrg = get_waktu_jkt().strftime("%d-%m-%Y %H:%M WIB")
        html_cetak = render_print_html(semua_kartu, judul_dok, waktu_skrg)
        components.html(html_cetak, height=650, scrolling=True)
    else:
        st.info("ℹ️ Seluruh lokasi yang dipilih sedang kosong (centang 'Sertakan kartu untuk rak kosong' jika tetap ingin mencetak kartu kosong).")
