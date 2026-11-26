import hmac

def _verifikasi_admin_ppic_wms(username_in, pin_in):
    try:
        admin_map = {str(k).strip(): str(v).strip() for k, v in dict(st.secrets["auth_admin_ppic"]).items()}
    except Exception:
        admin_map = {}
    if not admin_map:
        return False, "Konfigurasi [auth_admin_ppic] belum diatur di Streamlit Secrets."
    u_clean = str(username_in).strip()
    p_clean = str(pin_in).strip()
    for nama_adm, pass_adm in admin_map.items():
        if nama_adm.lower() == u_clean.lower():
            if hmac.compare_digest(p_clean, pass_adm):
                return True, nama_adm
            return False, "PIN Admin PPIC salah!"
    return False, f"Akun '{u_clean}' tidak terdaftar sebagai Admin PPIC."

@st.cache_data(ttl=60)
def _load_recent_outbound_wms(limit_n=30):
    q = (
        core.db.collection("log_mutasi_rak")
        .order_by("Timestamp", direction=firestore.Query.DESCENDING)
        .limit(limit_n)
        .stream()
    )
    items = []
    for doc in q:
        d = doc.to_dict() or {}
        jenis = str(d.get("Jenis_Mutasi") or d.get("Jenis") or "").upper()
        if "OUTBOUND" not in jenis:
            continue
        d["_doc_id"] = doc.id
        items.append(d)
    return items

def render_panel_retur_outbound_ppic(semua_data_rak, df_master):
    st.markdown("### ↩️ Retur Kelebihan Outbound ke Rak (Khusus Admin PPIC)")
    st.caption("Kembalikan palet kelebihan muat dari log transaksi Direct Outbound ke rak asal (atau rak alternatif jika rak asal sudah penuh).")

    if "wms_ppic_admin" not in st.session_state:
        st.session_state.wms_ppic_admin = None

    if not st.session_state.wms_ppic_admin:
        with st.container(border=True):
            st.warning("🔒 **Akses Terkunci:** Hanya **Admin PPIC** yang dapat melakukan pengembalian stok outbound.")
            with st.form("form_login_ppic_wms"):
                c1, c2, c3 = st.columns([2, 2, 1.2])
                with c1:
                    u_in = st.text_input("Username Admin PPIC:", placeholder="Cth: Antony")
                with c2:
                    p_in = st.text_input("PIN Admin PPIC:", type="password", placeholder="••••")
                with c3:
                    st.write("")
                    st.write("")
                    sub_btn = st.form_submit_button("🔓 BUKA AKSES", type="primary", use_container_width=True)
                if sub_btn:
                    ok, msg = _verifikasi_admin_ppic_wms(u_in, p_in)
                    if ok:
                        st.session_state.wms_ppic_admin = msg
                        st.rerun()
                    else:
                        st.error(f"❌ {msg}")
        return

    c_top1, c_top2 = st.columns([3, 1])
    with c_top1:
        st.success(f"👤 Admin PPIC Aktif: **{st.session_state.wms_ppic_admin}**")
    with c_top2:
        if st.button("🔒 Kunci Panel Retur", use_container_width=True, key="btn_lock_retur_wms"):
            st.session_state.wms_ppic_admin = None
            st.rerun()

    recent_outs = _load_recent_outbound_wms(30)
    if not recent_outs:
        st.info("Belum ada riwayat transaksi Outbound terbaru.")
        return

    opsi_logs = []
    for idx_o, lg in enumerate(recent_outs):
        ts_o = str(lg.get("Timestamp", "-"))
        kol_o = str(lg.get("Kolom", "-")).upper()
        bar_o = int(lg.get("Baris", 0) or 0)
        nm_o = str(lg.get("Nama Barang") or lg.get("Nama Produk") or "-")
        lot_o = str(lg.get("Lot Number") or "-")
        plt_o = int(lg.get("Pallet", 0) or 0)
        dus_o = int(lg.get("Dus", 0) or 0)
        ret_p_prev = int(lg.get("Returned_Pallet", 0) or 0)
        ret_d_prev = int(lg.get("Returned_Dus", 0) or 0)
        ket_o = str(lg.get("Keterangan", ""))

        sisa_p = max(0, plt_o - ret_p_prev)
        sisa_d = max(0, dus_o - ret_d_prev)
        st_ret = f" [Sudah Retur: {ret_p_prev}P {ret_d_prev}D]" if (ret_p_prev > 0 or ret_d_prev > 0) else ""
        opsi_logs.append(
            f"#{idx_o+1} | {ts_o} | Asal {kol_o}-{bar_o} | {nm_o} | Lot {lot_o} | "
            f"Keluar: {plt_o}P {dus_o}D (Sisa: {sisa_p}P {sisa_d}D){st_ret} — {ket_o[:40]}"
        )

    pilihan_lbl = st.selectbox("Pilih Log Transaksi Outbound yang Berlebih:", options=opsi_logs, key="sel_log_retur_wms")
    log_sel = recent_outs[opsi_logs.index(pilihan_lbl)]

    kol_asal = str(log_sel.get("Kolom", "")).upper()
    bar_asal = int(log_sel.get("Baris", 0) or 0)
    pn_ret = str(log_sel.get("Part Number", "")).upper()
    nm_ret = str(log_sel.get("Nama Barang") or log_sel.get("Nama Produk") or "")
    lot_ret = str(log_sel.get("Lot Number", ""))
    sat_ret = "Dus" if pn_ret.endswith(('D', 'G')) else "Sak"

    max_ret_p = max(0, int(log_sel.get("Pallet", 0) or 0) - int(log_sel.get("Returned_Pallet", 0) or 0))
    max_ret_d = max(0, int(log_sel.get("Dus", 0) or 0) - int(log_sel.get("Returned_Dus", 0) or 0))

    if max_ret_p == 0 and max_ret_d == 0:
        st.warning("⚠️ Seluruh kuantitas pada transaksi log ini sudah diretur sebelumnya.")
        return

    with st.container(border=True):
        st.markdown(f"**Item:** {nm_ret} (`{pn_ret}`) | **Lot:** `{lot_ret}` | **Rak Asal:** `{kol_asal}-{bar_asal}`")
        all_racks = [
            f"{k}-{b}" for b in range(1, 29) for k in ['A', 'B', 'C', 'D', 'E', 'F', 'G']
            if not (k == 'F' and b < 5) and not (k == 'G' and b < 17) and f"{k}-{b}" != f"{kol_asal}-{bar_asal}"
        ]
        opsi_rak = [f"{kol_asal}-{bar_asal} (Rak Asal)"] + all_racks

        cr1, cr2, cr3, cr4 = st.columns([1.2, 1.2, 1.5, 2.1])
        with cr1:
            in_p = st.number_input("Retur Palet Utuh:", min_value=0, max_value=max_ret_p, value=min(1, max_ret_p), step=1, key="wms_ret_p")
        with cr2:
            in_d = st.number_input(f"Retur Pecahan ({sat_ret}):", min_value=0, max_value=max_ret_d, value=0 if max_ret_p > 0 else max_ret_d, step=1, key="wms_ret_d")
        with cr3:
            tuj_sel = st.selectbox("Rak Tujuan Retur:", options=opsi_rak, key="wms_ret_tuj")
        with cr4:
            alasan = st.text_input("Alasan Retur:", placeholder="Cth: Armada penuh / batal kirim sebagian", key="wms_ret_alasan")

        if st.button("↩️ PROSES PENGEMBALIAN KE RAK", type="primary", use_container_width=True, key="btn_exec_retur_wms"):
            if in_p == 0 and in_d == 0:
                st.warning("⚠️ Masukkan minimal 1 palet atau pecahan yang diretur.")
            else:
                rak_clean = tuj_sel.split(" ")[0]
                k_tuj, b_tuj_s = rak_clean.split("-")
                b_tuj = int(b_tuj_s)

                doc_ref_tuj = core.db.collection(core.NAMA_DATABASE).document(f"Kolom_{k_tuj}")
                doc_ref_lg = core.db.collection("log_mutasi_rak").document(log_sel["_doc_id"])
                trx = core.db.transaction()

                try:
                    slot_baru = core.proses_retur_outbound_ke_rak(
                        trx, doc_ref_tuj, doc_ref_lg,
                        k_tuj, b_tuj, pn_ret, nm_ret, lot_ret,
                        in_p, in_d, sat_ret,
                        st.session_state.wms_ppic_admin,
                        alasan
                    )

                    tot_pcs_ret = 0
                    if not df_master.empty:
                        m_sub = df_master[df_master['Part Number'].astype(str).str.strip().str.upper() == pn_ret]
                        if not m_sub.empty:
                            mr = m_sub.iloc[0]
                            isi_p = int(mr.get('Total_Pcs_Pallet', 0) or 0)
                            isi_d = int(mr.get('Pcs_Per_Box', 0) or 0) if sat_ret == "Dus" else int(mr.get('Pcs_Per_Sac', 0) or 0)
                            tot_pcs_ret = (in_p * isi_p) + (in_d * isi_d)

                    core.catat_log_mutasi(
                        "RETUR OUTBOUND (PPIC)",
                        k_tuj, b_tuj, nm_ret, pn_ret, lot_ret,
                        in_p, in_d, tot_pcs_ret,
                        f"Admin PPIC: {st.session_state.wms_ppic_admin} | Ex Log {kol_asal}-{bar_asal} | {alasan}"
                    )

                    pec_s = f" + {in_d} {sat_ret}" if in_d > 0 else ""
                    core.kirim_notif_telegram(
                        f"↩️ <b>RETUR KELEBIHAN OUTBOUND - PPIC</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"📦 <b>Item:</b> {core.escape_html(nm_ret)}\n"
                        f"🏷️ <b>Lot:</b> <code>{core.escape_html(lot_ret)}</code>\n"
                        f"📍 <b>Masuk Rak:</b> <b>{k_tuj}-{b_tuj}</b> (Slot {slot_baru})\n"
                        f"📊 <b>Jumlah Retur:</b> <b>{in_p}P{pec_s}</b>\n"
                        f"👤 <b>Admin PPIC:</b> {core.escape_html(st.session_state.wms_ppic_admin)}\n"
                        f"📝 <b>Alasan:</b> <i>{core.escape_html(alasan or '-')}</i>"
                    )

                    _load_recent_outbound_wms.clear()
                    core.get_all_racking_data.clear()
                    st.success(f"✅ Berhasil mengembalikan **{in_p}P{pec_s}** ke **Rak {k_tuj}-{b_tuj}** (Slot {slot_baru})!")
                    st.rerun()
                except ValueError as ve:
                    st.error(f"❌ Gagal Retur: {ve}")
                except Exception as ex:
                    st.error(f"❌ Kesalahan Sistem: {ex}")
