"""Normalizador: salida cruda del actor → esquema interno (CLAUDE.md §5).

El actor clockworks/tiktok-profile-scraper devuelve UN ITEM POR VIDEO, con los
datos del perfil repetidos en `authorMeta`. Aquí los agrupamos por cuenta y
mapeamos los nombres de campo verificados con la corrida real del 2026-07-07:

    authorMeta.name  → handle          playCount    → views
    authorMeta.fans  → followers       diggCount    → likes
    authorMeta.heart → likesTotal      commentCount → comments
    authorMeta.video → videoCount      shareCount   → shares
    createTimeISO    → postedAt        text         → caption

Función pura (testeable) + un modo CLI para normalizar un crudo ya guardado:
    python src/normalize.py data/snapshots/raw/2026-07-07T0339-raw.json
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARPETA_SNAPSHOTS = ROOT / "data" / "snapshots"


def normalizar_items(items: list, fecha_iso: str) -> dict:
    """Agrupa los items crudos (uno por video) en el snapshot interno por cuenta.

    Items sin `authorMeta.name` (cuenta privada/borrada o error del actor) se
    registran en `errors` y NO abortan la normalización: se sigue con el resto.
    """
    cuentas: dict[str, dict] = {}
    errores: list[str] = []

    for item in items:
        autor = item.get("authorMeta") or {}
        handle = autor.get("name")
        if not handle:
            errores.append(
                f"item sin authorMeta.name (input={item.get('input')!r}, "
                f"error={item.get('error')!r})"
            )
            continue

        cuenta = cuentas.setdefault(handle, {
            "handle": handle,
            "followers": autor.get("fans"),
            "following": autor.get("following"),
            "likesTotal": autor.get("heart"),
            "videoCount": autor.get("video"),
            "verified": autor.get("verified", False),
            "videos": [],
        })
        cuenta["videos"].append({
            "id": item.get("id"),
            "postedAt": item.get("createTimeISO"),
            "views": item.get("playCount"),
            "likes": item.get("diggCount"),
            "comments": item.get("commentCount"),
            "shares": item.get("shareCount"),
            "caption": item.get("text"),
        })

    return {"date": fecha_iso, "accounts": list(cuentas.values()), "errors": errores}


def guardar_snapshot(snapshot: dict, fecha: str) -> Path:
    """Escribe el snapshot normalizado sin pisar uno existente (el histórico es sagrado)."""
    CARPETA_SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA_SNAPSHOTS / f"{fecha}.json"
    n = 2
    while ruta.exists():
        ruta = CARPETA_SNAPSHOTS / f"{fecha}-{n}.json"
        n += 1
    ruta.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return ruta


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python src/normalize.py data/snapshots/raw/<archivo>-raw.json")
        return 1
    ruta_cruda = Path(sys.argv[1])
    items = json.loads(ruta_cruda.read_text(encoding="utf-8"))

    # La fecha sale del nombre del crudo: 2026-07-07T0339-raw.json → 2026-07-07
    fecha = ruta_cruda.name[:10]
    hora = ruta_cruda.name[11:15]  # HHMM
    fecha_iso = f"{fecha}T{hora[:2]}:{hora[2:]}:00Z" if len(hora) == 4 else f"{fecha}T00:00:00Z"

    snapshot = normalizar_items(items, fecha_iso)
    ruta = guardar_snapshot(snapshot, fecha)

    print(f"[ok] snapshot normalizado: {ruta.relative_to(ROOT)}")
    for c in snapshot["accounts"]:
        print(f"  @{c['handle']}: {c['followers']:,} seguidores, "
              f"{len(c['videos'])} videos")
    for e in snapshot["errors"]:
        print(f"  [aviso] {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
