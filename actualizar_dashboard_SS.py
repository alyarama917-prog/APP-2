#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║   SCRIPT DE ACTUALIZACIÓN — DASHBOARD CEO SIDE SPORTS               ║
║   Consulta HubSpot y actualiza el archivo dashboard_CEO_SS_v31.html ║
╚══════════════════════════════════════════════════════════════════════╝

USO:
    pip install requests
    python actualizar_dashboard_SS.py

REQUISITOS:
    - HUBSPOT_API_KEY: tu API Key o Private App Token de HubSpot
    - dashboard_CEO_SS_v31.html en la misma carpeta (o ajusta DASHBOARD_FILE)

REGLAS (ver REGLAS_DASHBOARD_SS.md para detalle completo):
    - ALL_DEALS    : TODOS los deals creados en 2026 (incluye Perdidos/Dejó de Responder)
    - WON_2026     : Cierres Ganados P2025 + P2026, por fecha de CIERRE en 2026
    - MONTHLY      : contacts = HubSpot real | deals = todos | wonVal = por closedate
    - PIPE2026     : vertical y producto de ALL_DEALS, todos sin excepción
    - TOTALVAL     : deals sin Cierre Perdido ni Dejó de Responder, por closedate
                     Ivan: solo Pipeline 2026 | Cynthia+Jorge: P2025+P2026
"""

import requests
import json
import re
import os
from datetime import datetime

# ══════════════════════════════════════════════════
#  CONFIGURACIÓN — editar antes de correr
# ══════════════════════════════════════════════════
HUBSPOT_API_KEY = os.environ.get("HUBSPOT_API_KEY", "")  # Private App Token de HubSpot
DASHBOARD_FILE  = "index.html"                          # archivo a actualizar
OUTPUT_FILE     = "index.html"                          # puede ser el mismo archivo

# IDs de HubSpot (no cambiar)
ACCOUNT_ID      = "23609062"
PIPELINE_2026   = "840874328"
PIPELINE_2025   = "default"

OWNERS = {
    "Cynthia González":              "296131735",
    "Jorge Alberto Avalos González": "298457964",
    "Ivan Alejandro Leija":          "78705083",
}
OWNER_SHORT = {
    "296131735": "c",   # Cynthia
    "298457964": "j",   # Jorge
    "78705083":  "i",   # Ivan
}
OWNER_FULLNAME = {
    "296131735": "Cynthia González",
    "298457964": "Jorge Avalos",
    "78705083":  "Ivan Leija",
}

STAGES_WON      = ["closedwon", "1249322553"]
STAGES_LOST     = ["closedlost", "1249322554"]
STAGES_NOSHOW   = ["1249322551"]   # Dejó de Responder
STAGES_EXCLUDE  = STAGES_LOST + STAGES_NOSHOW   # excluir de TOTALVAL

MES_ACTUAL = "Marzo"   # ← cambiar al mes en curso cuando avance el año
YEAR       = "2026"

MESES_ES = {
    "01":"Enero","02":"Febrero","03":"Marzo","04":"Abril",
    "05":"Mayo","06":"Junio","07":"Julio","08":"Agosto",
    "09":"Septiembre","10":"Octubre","11":"Noviembre","12":"Diciembre"
}
MESES_ABREV = {
    "01":"Ene","02":"Feb","03":"Mar","04":"Abr",
    "05":"May","06":"Jun","07":"Jul","08":"Ago",
    "09":"Sep","10":"Oct","11":"Nov","12":"Dic"
}

# ══════════════════════════════════════════════════
#  CLIENTE HUBSPOT
# ══════════════════════════════════════════════════
HEADERS = {
    "Authorization": f"Bearer {HUBSPOT_API_KEY}",
    "Content-Type": "application/json"
}
BASE_URL = "https://api.hubapi.com"

def hs_search(object_type, filters, properties, limit=200):
    """Busca objetos en HubSpot con paginación automática."""
    results = []
    after = None
    while True:
        body = {
            "filterGroups": [{"filters": filters}],
            "properties": properties,
            "limit": limit,
        }
        if after:
            body["after"] = after
        r = requests.post(
            f"{BASE_URL}/crm/v3/objects/{object_type}/search",
            headers=HEADERS, json=body
        )
        r.raise_for_status()
        data = r.json()
        results.extend(data.get("results", []))
        paging = data.get("paging", {}).get("next", {})
        after = paging.get("after")
        if not after:
            break
    return results

def hs_count(object_type, filters):
    """Retorna solo el total (count) sin traer todos los objetos."""
    body = {
        "filterGroups": [{"filters": filters}],
        "properties": ["hs_object_id"],
        "limit": 1,
    }
    r = requests.post(
        f"{BASE_URL}/crm/v3/objects/{object_type}/search",
        headers=HEADERS, json=body
    )
    r.raise_for_status()
    return r.json().get("total", 0)

# ══════════════════════════════════════════════════
#  1. CONTACTOS POR VENDEDOR Y MES
# ══════════════════════════════════════════════════
def get_contacts_by_owner_month(owner_id, year=YEAR):
    """Retorna dict {mes_abrev: count} para un vendedor en el año."""
    contacts_by_month = {}
    for mm, nombre in MESES_ES.items():
        inicio = f"{year}-{mm}-01"
        # último día del mes
        if mm in ["01","03","05","07","08","10","12"]:
            fin = f"{year}-{mm}-31"
        elif mm in ["04","06","09","11"]:
            fin = f"{year}-{mm}-30"
        else:  # Febrero
            fin = f"{year}-{mm}-28"

        count = hs_count("contacts", [
            {"propertyName": "createdate", "operator": "BETWEEN",
             "value": f"{inicio}T00:00:00.000Z", "highValue": f"{fin}T23:59:59.999Z"},
            {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id}
        ])
        contacts_by_month[nombre] = count
        print(f"  Contactos {OWNER_FULLNAME.get(owner_id,'?')} {nombre}: {count}")
    return contacts_by_month

# ══════════════════════════════════════════════════
#  2. DEALS — ALL_DEALS y WON_2026
# ══════════════════════════════════════════════════
def get_all_deals(year=YEAR):
    """Trae todos los deals creados en el año del Pipeline 2026."""
    deals_raw = hs_search("deals", [
        {"propertyName": "createdate", "operator": "BETWEEN",
         "value": f"{year}-01-01T00:00:00.000Z",
         "highValue": f"{year}-12-31T23:59:59.999Z"},
        {"propertyName": "pipeline", "operator": "EQ", "value": PIPELINE_2026}
    ], ["dealname","amount","dealstage","hubspot_owner_id",
        "createdate","closedate","pipeline"])
    return deals_raw

def get_won_deals(year=YEAR):
    """
    Trae cierres ganados de AMBOS pipelines (P2025 + P2026)
    con closedate en el año.
    REGLA: wonVal siempre incluye P2025 + P2026.
    Ivan es la excepción solo para TOTALVAL, no para wonVal.
    """
    won = []
    for pipeline in [PIPELINE_2026, PIPELINE_2025]:
        stage = "1249322553" if pipeline == PIPELINE_2026 else "closedwon"
        raw = hs_search("deals", [
            {"propertyName": "closedate", "operator": "BETWEEN",
             "value": f"{year}-01-01T00:00:00.000Z",
             "highValue": f"{year}-12-31T23:59:59.999Z"},
            {"propertyName": "pipeline", "operator": "EQ", "value": pipeline},
            {"propertyName": "dealstage", "operator": "EQ", "value": stage}
        ], ["dealname","amount","hubspot_owner_id","closedate","pipeline"])
        won.extend(raw)
    return won

# ══════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════
def parse_date_month(date_str, abrev=False):
    """'2026-03-15T...' → 'Marzo' o 'Mar'"""
    if not date_str:
        return "—"
    mm = date_str[5:7]
    return MESES_ABREV.get(mm, "—") if abrev else MESES_ES.get(mm, "—")

def owner_key(owner_id):
    return OWNER_SHORT.get(str(owner_id), "c")

def safe_amt(props):
    try:
        return float(props.get("amount") or 0)
    except:
        return 0.0

def stage_label(dealstage):
    MAP = {
        "1249322553": "Cierre Ganado",
        "1249322554": "Cierre Perdido",
        "1249322551": "Dejó de Responder",
        "closedwon":  "Cierre Ganado",
        "closedlost": "Cierre Perdido",
    }
    return MAP.get(dealstage, dealstage or "—")

# ══════════════════════════════════════════════════
#  3. CONSTRUIR BLOQUES JS
# ══════════════════════════════════════════════════

def build_all_deals_js(deals_raw, existing_deals_js=""):
    """
    Construye el bloque JS de ALL_DEALS.
    IMPORTANTE: vertical y producto NO vienen de HubSpot — se mantienen
    del dashboard anterior. Si hay deals nuevos, se agregan sin vertical/producto
    y deben completarse manualmente.
    """
    # Parsear deals existentes para preservar vertical/producto
    existing = {}
    pattern = re.findall(
        r'\{n:"([^"]+)".*?vertical:"([^"]+)".*?producto:"([^"]+)".*?createOrder:(\d+)',
        existing_deals_js, re.DOTALL
    )
    for n, v, p, order in pattern:
        existing[n.strip()] = {"vertical": v, "producto": p, "createOrder": int(order)}

    lines = ["const ALL_DEALS = ["]
    order = 1
    for d in sorted(deals_raw, key=lambda x: x["properties"].get("createdate","") or ""):
        p       = d["properties"]
        name    = (p.get("dealname") or "").strip()
        owner   = p.get("hubspot_owner_id","")
        owner_n = OWNER_FULLNAME.get(str(owner), owner)
        amt     = safe_amt(p)
        stage   = stage_label(p.get("dealstage",""))
        c_month = parse_date_month(p.get("createdate",""))
        cl_month= parse_date_month(p.get("closedate",""), abrev=True)

        # Preservar vertical y producto si ya existían
        ex      = existing.get(name, {})
        vertical= ex.get("vertical","— COMPLETAR —")
        producto= ex.get("producto","— COMPLETAR —")
        existing_order = ex.get("createOrder", order)

        lines.append(
            f'  {{n:"{name}", o:"{owner_n}", amt:{int(amt)}, '
            f'stage:"{stage}", createMonth:"{c_month}", closeMonth:"{cl_month}", '
            f'vertical:"{vertical}", producto:"{producto}", createOrder:{existing_order}}},'
        )
        order += 1

    lines.append("];")
    return "\n".join(lines)


def build_won_2026_js(won_raw):
    """Construye el bloque JS de WON_2026."""
    lines = ["const WON_2026 = ["]
    for d in sorted(won_raw, key=lambda x: x["properties"].get("closedate","") or ""):
        p       = d["properties"]
        name    = (p.get("dealname") or "").strip()
        owner   = p.get("hubspot_owner_id","")
        owner_n = OWNER_FULLNAME.get(str(owner), owner)
        amt     = safe_amt(p)
        cl_month= parse_date_month(p.get("closedate",""))
        lines.append(
            f'  {{n:"{name}", owner:"{owner_n}", amount:{int(amt)}, closeMonth:"{cl_month}"}},'
        )
    lines.append("];")
    return "\n".join(lines)


def build_monthly_js(all_deals, won_deals, contacts_by_owner):
    """
    Construye MONTHLY con los 4 campos por vendedor por mes.
    contacts_by_owner = {"c": {"Enero":69,...}, "j": {...}, "i": {...}}
    """
    MESES_ORDER = ["Ene","Feb","Mar","Abr","May","Jun",
                   "Jul","Ago","Sep","Oct","Nov","Dic"]
    MESES_FULL  = {
        "Ene":"Enero","Feb":"Febrero","Mar":"Marzo","Abr":"Abril",
        "May":"Mayo","Jun":"Junio","Jul":"Julio","Ago":"Agosto",
        "Sep":"Septiembre","Oct":"Octubre","Nov":"Noviembre","Dic":"Diciembre"
    }
    MESES_LABEL = {
        "Ene":"Enero 2026","Feb":"Febrero 2026","Mar":"Marzo 2026",
        "Abr":"Abril 2026","May":"Mayo 2026","Jun":"Junio 2026",
        "Jul":"Julio 2026","Ago":"Agosto 2026","Sep":"Septiembre 2026",
        "Oct":"Octubre 2026","Nov":"Noviembre 2026","Dic":"Diciembre 2026"
    }

    # Indexar deals por mes de creación y vendedor
    deals_idx = {}   # {abrev_mes: {owner_key: [deal,...]}}
    for d in all_deals:
        p = d["properties"]
        mes_full = parse_date_month(p.get("createdate",""))
        abrev    = next((k for k,v in MESES_FULL.items() if v==mes_full), None)
        if not abrev: continue
        ok = owner_key(p.get("hubspot_owner_id",""))
        deals_idx.setdefault(abrev, {}).setdefault(ok, []).append(d)

    # Indexar won por mes de cierre y vendedor
    won_idx = {}     # {mes_full: {owner_key: [deal,...]}}
    for d in won_deals:
        p = d["properties"]
        mes_full = parse_date_month(p.get("closedate",""))
        ok = owner_key(p.get("hubspot_owner_id",""))
        won_idx.setdefault(mes_full, {}).setdefault(ok, []).append(d)

    lines = [
        "// REGLA MONTHLY: contacts = contactos asignados al vendedor creados ese mes (fuente HubSpot)",
        "// REGLA MONTHLY: deals    = TODOS los negocios creados en el mes (incluyendo Perdidos/Dejó de Responder)",
        "// REGLA MONTHLY: totalVal = suma de montos de todos los deals creados en el mes (sin filtro de etapa)",
        "// REGLA MONTHLY: wonVal   = Cierres Ganados P2025+P2026 por fecha de CIERRE en ese mes",
        "const MONTHLY = {"
    ]

    # Calcular acumulados para Anio
    anio = {ok: {"contacts":0,"deals":0,"won":0,"wonVal":0,"totalVal":0}
            for ok in ["c","j","i"]}

    for abrev in MESES_ORDER:
        mes_full = MESES_FULL[abrev]
        label    = MESES_LABEL[abrev]
        row_parts = []

        for ok in ["c","j","i"]:
            d_list = deals_idx.get(abrev, {}).get(ok, [])
            w_list = won_idx.get(mes_full, {}).get(ok, [])

            contacts  = contacts_by_owner.get(ok, {}).get(mes_full, 0)
            n_deals   = len(d_list)
            won_cnt   = len(w_list)
            won_val   = sum(safe_amt(d["properties"]) for d in w_list)
            total_val = sum(safe_amt(d["properties"]) for d in d_list)

            anio[ok]["contacts"]  += contacts
            anio[ok]["deals"]     += n_deals
            anio[ok]["won"]       += won_cnt
            anio[ok]["wonVal"]    += won_val
            anio[ok]["totalVal"]  += total_val

            row_parts.append(
                f'{ok}:{{contacts:{contacts},deals:{n_deals},won:{won_cnt},'
                f'wonVal:{int(won_val)},totalVal:{int(total_val)}}}'
            )

        row = ", ".join(row_parts)
        lines.append(f'  {abrev}:  {{ label:"{label}",    {row} }},')

    # Fila Anio
    anio_parts = []
    for ok in ["c","j","i"]:
        a = anio[ok]
        anio_parts.append(
            f'{ok}:{{contacts:{a["contacts"]},deals:{a["deals"]},won:{a["won"]},'
            f'wonVal:{int(a["wonVal"])},totalVal:{int(a["totalVal"])}}}'
        )
    lines.append(f'  Anio: {{ label:"Año 2026",      {", ".join(anio_parts)} }},')
    lines.append("};")
    return "\n".join(lines)


def build_sum_js(all_deals, won_deals, contacts_by_owner):
    """Construye el bloque SUM para los filtros month/q1/q2/year."""
    PERIODS = {
        "month": [MES_ACTUAL],
        "q1":    ["Enero","Febrero","Marzo"],
        "q2":    ["Abril","Mayo","Junio"],
        "year":  list(MESES_ES.values()),
    }
    WON_MONTHS = {
        "month": [MES_ACTUAL],
        "q1":    ["Enero","Febrero","Marzo"],
        "q2":    ["Abril","Mayo","Junio"],
        "year":  list(MESES_ES.values()),
    }

    lines = ["const SUM = {"]
    for period, create_months in PERIODS.items():
        won_months = WON_MONTHS[period]
        row_parts  = []

        for ok in ["c","j","i"]:
            owner_fullname = next(n for n,id_ in OWNERS.items()
                                  if OWNER_SHORT.get(id_)==ok)

            d_list = [d for d in all_deals
                      if parse_date_month(d["properties"].get("createdate","")) in create_months
                      and owner_key(d["properties"].get("hubspot_owner_id",""))==ok]

            w_list = [d for d in won_deals
                      if parse_date_month(d["properties"].get("closedate","")) in won_months
                      and owner_key(d["properties"].get("hubspot_owner_id",""))==ok]

            contacts  = sum(contacts_by_owner.get(ok,{}).get(m,0) for m in create_months)
            n_deals   = len(d_list)
            won_cnt   = len(w_list)
            won_val   = sum(safe_amt(d["properties"]) for d in w_list)
            total_val = sum(safe_amt(d["properties"]) for d in d_list)

            row_parts.append(
                f'{ok}:{{contacts:{contacts},deals:{n_deals},won:{won_cnt},'
                f'accepted:0,wonVal:{int(won_val)},totalVal:{int(total_val)}}}'
            )

        lines.append(f'  {period}: {{ {", ".join(row_parts)} }},')

    lines.append("};")
    return "\n".join(lines)


def build_pipe2026_js(all_deals):
    """
    Construye PIPE2026 agrupando verticales y productos.
    REGLA: usa TODOS los deals sin excluir ninguna etapa.
    """
    PERIODS = {
        "mar":  ["Marzo"],
        "q1":   ["Enero","Febrero","Marzo"],
        "q2":   ["Abril","Mayo","Junio"],
        "year": list(MESES_ES.values()),
    }

    lines = [
        "// REGLA PIPE2026: usa TODOS los 24 deals (incluyendo Cierre Perdido/Dejó de Responder)",
        "const PIPE2026 = {"
    ]

    for period, months in PERIODS.items():
        subset = [d for d in all_deals
                  if parse_date_month(d["properties"].get("createdate","")) in months]

        vc, vv, pc, pv = {}, {}, {}, {}
        for d in subset:
            p = d["properties"]
            # vertical y producto se deben leer del HTML existente
            # aquí los dejamos vacíos para que el script los preserve del HTML
            amt = safe_amt(p)

        if not subset:
            lines.append(f'  {period}: {{ vc:{{}}, vv:{{}}, pc:{{}}, pv:{{}} }},')
        else:
            # NOTA: vertical/producto no están en HubSpot, se preservan del HTML
            lines.append(f'  {period}: {{ vc:{json.dumps(vc)}, vv:{json.dumps(vv)}, pc:{json.dumps(pc)}, pv:{json.dumps(pv)} }},')

    lines.append("};")
    return "\n".join(lines)


# ══════════════════════════════════════════════════
#  4. INYECTAR EN EL HTML
# ══════════════════════════════════════════════════
def replace_js_block(html, const_name, new_block):
    """Reemplaza un bloque 'const NAME = ...' en el HTML."""
    # Buscar inicio
    start_marker = f"const {const_name} = "
    idx_start = html.find(start_marker)
    if idx_start < 0:
        print(f"  ⚠ No encontrado: {const_name}")
        return html

    # Buscar fin del bloque (línea con solo '};' o '];')
    search_from = idx_start + len(start_marker)
    idx_end = -1
    for end_marker in ["\n];", "\n};"]:
        pos = html.find(end_marker, search_from)
        if pos >= 0:
            if idx_end < 0 or pos < idx_end:
                idx_end = pos + len(end_marker)

    if idx_end < 0:
        print(f"  ⚠ No se encontró el fin del bloque: {const_name}")
        return html

    html = html[:idx_start] + new_block + html[idx_end:]
    print(f"  ✅ {const_name} actualizado")
    return html


# ══════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("  ACTUALIZANDO DASHBOARD CEO SIDE SPORTS")
    print(f"  Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # Verificar que el archivo existe
    if not os.path.exists(DASHBOARD_FILE):
        print(f"\n❌ No se encontró: {DASHBOARD_FILE}")
        print("   Asegúrate de tener el archivo en la misma carpeta.")
        return

    with open(DASHBOARD_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    print(f"\n📂 Dashboard cargado: {len(html):,} bytes")

    # Verificar API Key
    if HUBSPOT_API_KEY == "TU_API_KEY_AQUI":
        print("\n❌ Configura HUBSPOT_API_KEY en la línea 47 del script.")
        return

    # ── 1. Contactos por vendedor y mes ──────────────
    print("\n📞 Consultando contactos por vendedor y mes...")
    contacts_by_owner = {}
    for ok, owner_id in [("c","296131735"),("j","298457964"),("i","78705083")]:
        contacts_by_owner[ok] = get_contacts_by_owner_month(owner_id)

    # ── 2. Deals ──────────────────────────────────────
    print("\n💼 Consultando deals Pipeline 2026...")
    all_deals_raw = get_all_deals()
    print(f"   Total deals encontrados: {len(all_deals_raw)}")

    print("\n🏆 Consultando cierres ganados (P2025 + P2026)...")
    won_deals_raw = get_won_deals()
    print(f"   Total cierres ganados: {len(won_deals_raw)}")

    # Extraer ALL_DEALS actual del HTML (para preservar vertical/producto)
    idx_ad = html.find("const ALL_DEALS = [")
    end_ad = html.find("];", idx_ad) + 2
    existing_all_deals = html[idx_ad:end_ad] if idx_ad >= 0 else ""

    # ── 3. Construir bloques JS ───────────────────────
    print("\n🔧 Construyendo bloques JS...")
    all_deals_js = build_all_deals_js(all_deals_raw, existing_all_deals)
    won_2026_js  = build_won_2026_js(won_deals_raw)
    monthly_js   = build_monthly_js(all_deals_raw, won_deals_raw, contacts_by_owner)
    sum_js       = build_sum_js(all_deals_raw, won_deals_raw, contacts_by_owner)

    # PIPE2026: vertical/producto no están en HubSpot
    # Se recalcula desde ALL_DEALS existente (que preserva vertical/producto)
    print("\n📊 PIPE2026 se preserva del dashboard existente")
    print("   (vertical y producto no están en HubSpot — completar manualmente si hay deals nuevos)")

    # ── 4. Inyectar en el HTML ────────────────────────
    print("\n💉 Inyectando datos en el HTML...")
    html = replace_js_block(html, "ALL_DEALS", all_deals_js)
    html = replace_js_block(html, "WON_2026",  won_2026_js)
    html = replace_js_block(html, "MONTHLY",   monthly_js)
    html = replace_js_block(html, "SUM",        sum_js)
    # TOTALVAL y PIPE2026 requieren datos manuales — no se tocan automáticamente

    # ── 5. Guardar ────────────────────────────────────
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ Dashboard actualizado: {OUTPUT_FILE} ({len(html):,} bytes)")
    print("\n⚠️  REVISAR MANUALMENTE:")
    print("   1. Deals nuevos: asignar vertical y producto en ALL_DEALS")
    print("   2. Recalcular PIPE2026 si hubo deals nuevos")
    print("   3. Actualizar TOTALVAL si cambiaron las proyecciones")
    print("   4. Si cambió el mes en curso, actualizar MES_ACTUAL en línea 71")
    print("\n📋 Ver REGLAS_DASHBOARD_SS.md para referencia completa.")
    print("=" * 60)


if __name__ == "__main__":
    main()
