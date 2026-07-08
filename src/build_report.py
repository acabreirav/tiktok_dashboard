"""Genera docs/data.json a partir de TODOS los snapshots (CLAUDE.md §3).

Lee data/snapshots/*.json (la "base de datos"), calcula las métricas por
ventana (7/14/30 días) con las funciones puras de metrics.py, y escribe un
único JSON ya computado que el dashboard solo tiene que pintar.

Correr con:  python src/build_report.py
"""

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from metrics import (
    aceleracion,
    cadencia_semanal,
    crecimiento_seguidores,
    delta_views_total,
    detectar_breakouts,
    engagement_rate,
    mediana,
    ultima_publicacion,
    velocidad_views,
    views_por_seguidor,
)

ROOT = Path(__file__).resolve().parent.parent
CARPETA_SNAPSHOTS = ROOT / "data" / "snapshots"
CARPETA_IG = CARPETA_SNAPSHOTS / "instagram"
RUTA_LEGISLADORES = ROOT / "config" / "legisladores.csv"
RUTA_SALIDA = ROOT / "docs" / "data.json"

VENTANAS = (7, 14, 30)


def cargar_roster() -> list[dict]:
    """Base completa de legisladores desde config/legisladores.csv.

    Incluye a quienes NO tienen cuenta (handle=None): la ausencia de TikTok
    es un dato del producto (sección "terreno cedido" y cobertura por bloque).
    """
    if not RUTA_LEGISLADORES.exists():
        return []
    with open(RUTA_LEGISLADORES, encoding="utf-8") as f:
        filas = csv.DictReader(f)
        return [
            {
                "nombre": f_["nombre"],
                "cargo": f_["cargo"],
                "territorio": f_["territorio"],
                "partido": f_["partido"],
                "coalicion": f_["coalicion"],
                "sector": f_["sector"],
                "handle": (h if (h := f_["handle_tiktok"].strip()) not in ("", "sin cuenta")
                           else None),
                "handleInstagram": (
                    hi if (hi := f_.get("handle_instagram", "").strip())
                    not in ("", "sin cuenta") else None
                ),
            }
            for f_ in filas
        ]


def cargar_metadata() -> dict[str, dict]:
    """Ficha política por handle (solo quienes tienen cuenta), para el join."""
    return {leg["handle"]: {k: v for k, v in leg.items() if k != "handle"}
            for leg in cargar_roster() if leg["handle"]}


def cargar_snapshots_ig() -> list[dict]:
    """Snapshots de perfil Instagram, ordenados por fecha (puede no haber ninguno)."""
    if not CARPETA_IG.exists():
        return []
    snaps = [json.loads(r.read_text(encoding="utf-8"))
             for r in sorted(CARPETA_IG.glob("*.json"))]
    return sorted(snaps, key=lambda s: s["date"])


def instagram_por_handle(snapshots_ig: list[dict], fecha_fin: str, dias: int) -> dict:
    """Seguidores IG actuales + crecimiento de la ventana, por handle de IG.

    Misma lógica de línea base por cuenta que TikTok: primera aparición
    del handle dentro de la ventana vs el último snapshot IG disponible.
    """
    if not snapshots_ig:
        return {}
    limite = _ts(fecha_fin) - dias * 86400
    en_ventana = [s for s in snapshots_ig if _ts(s["date"]) >= limite]
    if not en_ventana:
        en_ventana = snapshots_ig[-1:]  # IG puede tener menos historia que TikTok
    ultimo = en_ventana[-1]

    resultado = {}
    for perfil in ultimo["profiles"]:
        handle = perfil["handle"]
        inicial = next(
            (p for s in en_ventana for p in s["profiles"]
             if p["handle"] == handle and s is not ultimo),
            None,
        )
        resultado[handle] = {
            "followers": perfil.get("followers"),
            "posts": perfil.get("posts"),
            "crecimiento": crecimiento_seguidores(
                inicial.get("followers") if inicial else None,
                perfil.get("followers") if inicial else None,
            ),
        }
    return resultado


def cargar_snapshots() -> list[dict]:
    """Todos los snapshots normalizados, ordenados por fecha (los crudos
    viven en raw/ y no se tocan aquí)."""
    rutas = sorted(CARPETA_SNAPSHOTS.glob("*.json"))
    snapshots = [json.loads(r.read_text(encoding="utf-8")) for r in rutas]
    return sorted(snapshots, key=lambda s: s["date"])


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _cuenta_en(snapshot: dict, handle: str) -> dict | None:
    return next((c for c in snapshot["accounts"] if c["handle"] == handle), None)


def calcular_ventana(snapshots: list[dict], dias: int, metadata: dict,
                     snapshots_ig: list[dict]) -> dict:
    """Métricas de todas las cuentas para una ventana que termina en el
    último snapshot y arranca `dias` antes."""
    ultimo = snapshots[-1]
    fecha_fin = ultimo["date"]
    limite = _ts(fecha_fin) - dias * 86400
    en_ventana = [s for s in snapshots if _ts(s["date"]) >= limite]
    hay_crecimiento = len(en_ventana) >= 2  # con una sola foto no hay deltas
    fecha_inicio_ventana = datetime.fromtimestamp(limite, tz=timezone.utc) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    ig = instagram_por_handle(snapshots_ig, fecha_fin, dias)

    cuentas = []
    for cuenta in ultimo["accounts"]:
        handle = cuenta["handle"]
        # Línea base POR CUENTA: su primera aparición dentro de la ventana
        # (la lista de cuentas puede cambiar entre snapshots; comparar contra
        # un snapshot donde la cuenta no existe daría deltas vacíos).
        primero = next((s for s in en_ventana if _cuenta_en(s, handle)), None)
        inicial = None
        if primero is not None and primero is not ultimo:
            inicial = _cuenta_en(primero, handle)
        dias_reales = ((_ts(fecha_fin) - _ts(primero["date"])) / 86400
                       if primero is not None else 0)
        serie = [
            (s["date"], c["followers"])
            for s in en_ventana
            if (c := _cuenta_en(s, handle)) and c["followers"] is not None
        ]
        meta = metadata.get(handle)
        cuentas.append({
            "handle": handle,
            "legislador": meta,  # ficha política o null
            # presencia en Instagram (solo perfil), si el legislador tiene IG
            "instagram": ig.get(meta["handleInstagram"]) if meta and meta.get("handleInstagram") else None,
            "verified": cuenta.get("verified", False),
            "followers": cuenta["followers"],
            "crecimiento": crecimiento_seguidores(
                inicial["followers"] if inicial else None,
                cuenta["followers"] if inicial else None,
            ),
            "aceleracion": aceleracion(serie),
            "engagement": engagement_rate(cuenta["videos"]),
            "velocidad": velocidad_views(
                inicial["videos"] if inicial else [],
                cuenta["videos"], dias_reales, cuenta["followers"],
            ),
            "cadencia": cadencia_semanal(cuenta["videos"], dias, fecha_fin),
            "viewsPorSeguidor": views_por_seguidor(cuenta["videos"], cuenta["followers"]),
            "breakouts": detectar_breakouts(cuenta["videos"], fecha_inicio_ventana, fecha_fin),
            "serieSeguidores": serie,
            # share of voice individual: views nuevas capturadas en el período
            "deltaViews": delta_views_total(
                inicial["videos"] if inicial else [], cuenta["videos"],
                primero["date"] if primero else fecha_fin,
            ),
            "ultimaPublicacion": ultima_publicacion(cuenta["videos"]),
            # top 5 videos por views, para la ficha individual del dashboard
            "videosTop": [
                {"caption": (v.get("caption") or "")[:140], "views": v["views"],
                 "likes": v.get("likes"), "postedAt": v.get("postedAt")}
                for v in sorted((v for v in cuenta["videos"] if v.get("views") is not None),
                                key=lambda v: -v["views"])[:5]
            ],
        })

    return {
        "days": dias,
        "snapshotsEnVentana": len(en_ventana),
        "hasGrowth": hay_crecimiento,
        # perfiles IG por handle de la ventana (incluye legisladores sin TikTok)
        "instagram": ig,
        "accounts": cuentas,
        "insights": generar_insights(cuentas, dias),
        "alertas": generar_alertas(cuentas),
        "titulares": generar_titulares(cuentas),
    }


# ---------- capa calculada de insights (determinística, gratis — §9) ----------

def _fmt(n: float, dec: int = 1) -> str:
    return f"{n:,.{dec}f}".rstrip("0").rstrip(".")


def generar_insights(cuentas: list[dict], dias: int) -> list[str]:
    frases = []

    con_crecimiento = [c for c in cuentas if c["crecimiento"] and c["crecimiento"]["porcentual"] is not None]
    if con_crecimiento:
        top = max(con_crecimiento, key=lambda c: c["crecimiento"]["porcentual"])
        frases.append(
            f"@{top['handle']} lidera el crecimiento de la ventana de {dias} días: "
            f"{'+' if top['crecimiento']['absoluto'] >= 0 else ''}"
            f"{top['crecimiento']['absoluto']:,} seguidores "
            f"({_fmt(top['crecimiento']['porcentual'], 2)}%)."
        )
    else:
        frases.append(
            "Todavía hay una sola foto: las tasas de crecimiento aparecerán "
            "cuando exista un segundo snapshot (el pipeline las calcula solo)."
        )

    for c in cuentas:
        if c["aceleracion"]["estado"] == "acelera":
            frases.append(f"@{c['handle']} está acelerando: la segunda mitad del período creció más que la primera.")
        elif c["aceleracion"]["estado"] == "enfria":
            frases.append(f"@{c['handle']} se está enfriando: su crecimiento perdió ritmo dentro del período.")

    rendidores = [c for c in cuentas if c["viewsPorSeguidor"] is not None and c["viewsPorSeguidor"] > 1]
    for c in rendidores:
        frases.append(
            f"@{c['handle']} rinde sobre su tamaño: su video típico hace "
            f"{_fmt(c['viewsPorSeguidor'])}× views que seguidores tiene."
        )

    for c in cuentas:
        if c["breakouts"]:
            b = c["breakouts"][0]
            frases.append(
                f"Breakout en @{c['handle']}: un video con {b['views']:,} views, "
                f"{_fmt(b['ratio'])}× la mediana de la cuenta."
            )

    engs = [(c["handle"], c["engagement"]) for c in cuentas if c["engagement"] is not None]
    if len(engs) >= 2:
        top_eng = max(engs, key=lambda e: e[1])
        frases.append(f"El engagement más alto es de @{top_eng[0]}: {_fmt(top_eng[1], 2)}% mediano por video.")

    return frases


def generar_alertas(cuentas: list[dict]) -> list[dict]:
    alertas = []
    for c in cuentas:
        if c["aceleracion"]["estado"] == "acelera":
            alertas.append({"tipo": "aceleracion", "handle": c["handle"],
                            "texto": "Aceleración fuerte de seguidores"})
        if c["aceleracion"]["estado"] == "enfria":
            alertas.append({"tipo": "enfriamiento", "handle": c["handle"],
                            "texto": "El crecimiento se está enfriando"})
        for b in c["breakouts"]:
            alertas.append({"tipo": "breakout", "handle": c["handle"],
                            "texto": f"Video breakout: {b['views']:,} views ({_fmt(b['ratio'])}× su mediana)"})
    return alertas


def generar_titulares(cuentas: list[dict]) -> dict:
    def top(clave, filtro=lambda c: True):
        candidatos = [c for c in cuentas if filtro(c) and clave(c) is not None]
        return max(candidatos, key=clave) if candidatos else None

    crecimiento = top(lambda c: c["crecimiento"]["porcentual"] if c["crecimiento"] else None)
    acelera = top(lambda c: c["aceleracion"]["ratio"],
                  lambda c: c["aceleracion"]["estado"] == "acelera")
    rinde = top(lambda c: c["viewsPorSeguidor"])

    breakout, cuenta_breakout = None, None
    for c in cuentas:
        for b in c["breakouts"]:
            if breakout is None or b["ratio"] > breakout["ratio"]:
                breakout, cuenta_breakout = b, c["handle"]

    return {
        "mayorCrecimiento": {
            "handle": crecimiento["handle"],
            "pct": crecimiento["crecimiento"]["porcentual"],
            "abs": crecimiento["crecimiento"]["absoluto"],
        } if crecimiento else None,
        "breakoutMasCaliente": {
            "handle": cuenta_breakout, "views": breakout["views"], "ratio": breakout["ratio"],
        } if breakout else None,
        "mayorAceleracion": {
            "handle": acelera["handle"], "ratio": acelera["aceleracion"]["ratio"],
        } if acelera else None,
        "rindeSobreTamano": {
            "handle": rinde["handle"], "viewsPorSeguidor": rinde["viewsPorSeguidor"],
        } if rinde else None,
    }


def main() -> int:
    snapshots = cargar_snapshots()
    if not snapshots:
        print("[error] No hay snapshots en data/snapshots/. Corre antes: python src/fetch.py")
        return 1

    data = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshots": {
            "count": len(snapshots),
            "first": snapshots[0]["date"],
            "last": snapshots[-1]["date"],
        },
        # base completa (incluye "sin cuenta") para cobertura y terreno cedido
        "roster": cargar_roster(),
        "windows": {str(d): calcular_ventana(snapshots, d, cargar_metadata(),
                                             cargar_snapshots_ig())
                    for d in VENTANAS},
    }

    RUTA_SALIDA.parent.mkdir(parents=True, exist_ok=True)
    RUTA_SALIDA.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    v7 = data["windows"]["7"]
    print(f"[ok] docs/data.json generado — {len(snapshots)} snapshot(s), "
          f"{len(v7['accounts'])} cuentas")
    print(f"  crecimiento calculable: {'sí' if v7['hasGrowth'] else 'todavía no (falta una 2ª foto)'}")
    print(f"  insights: {len(v7['insights'])} · alertas: {len(v7['alertas'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
