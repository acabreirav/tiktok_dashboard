"""Fase 1 — fetch mínimo: trae perfil + videos recientes de las cuentas configuradas.

Primera etapa (esta): guardar el JSON CRUDO que devuelve el actor de Apify en
data/snapshots/raw/, para inspeccionarlo antes de escribir el normalizador
(los nombres de campo varían entre actors — no se asume el esquema, se verifica).

Correr con:  python src/fetch.py            (pide confirmación antes de gastar)
             python src/fetch.py --videos 5 (menos videos por cuenta = más barato)

Guardas de costo:
- Muestra el plan y pide confirmación explícita antes de llamar a Apify.
- Limita los videos recientes por cuenta (default 10).
- Aborta si hay más de 5 cuentas configuradas (esta fase es solo para 2-3).
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from apify_client import ApifyError, correr_actor
from normalize import guardar_snapshot, normalizar_items

ROOT = Path(__file__).resolve().parent.parent
RUTA_CUENTAS = ROOT / "config" / "accounts.json"
CARPETA_RAW = ROOT / "data" / "snapshots" / "raw"

# Actor elegido como primer candidato (ver CLAUDE.md §6): devuelve perfil
# y videos recientes en una sola corrida. Si el test muestra mala salida
# o costo alto, probamos apidojo/tiktok-scraper.
ACTOR = "clockworks/tiktok-profile-scraper"

MAX_CUENTAS_FASE_1 = 5


def cargar_cuentas() -> list[str]:
    data = json.loads(RUTA_CUENTAS.read_text(encoding="utf-8"))
    return data["accounts"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot crudo desde Apify")
    parser.add_argument("--videos", type=int, default=10,
                        help="videos recientes por cuenta (default 10)")
    parser.add_argument("--si", action="store_true",
                        help="no pedir confirmación (para automatización futura)")
    args = parser.parse_args()

    # Token desde .env (local). En GitHub Actions vendrá como variable de entorno.
    load_dotenv(ROOT / ".env")
    import os
    token = os.getenv("APIFY_TOKEN")
    if not token:
        print("[error] No hay APIFY_TOKEN. Copia .env.example a .env y pega tu token.")
        return 1

    cuentas = cargar_cuentas()
    if len(cuentas) > MAX_CUENTAS_FASE_1:
        print(f"[error] Hay {len(cuentas)} cuentas configuradas; en Fase 1 el "
              f"límite es {MAX_CUENTAS_FASE_1}. Reduce config/accounts.json.")
        return 1

    # --- Guarda de costo: mostrar el plan y confirmar antes de gastar ---
    resultados_estimados = len(cuentas) * (1 + args.videos)
    print("Plan de la corrida:")
    print(f"  actor:    {ACTOR}")
    print(f"  cuentas:  {len(cuentas)} ({', '.join(cuentas)})")
    print(f"  videos:   hasta {args.videos} por cuenta")
    print(f"  items estimados: ~{resultados_estimados} "
          "(el costo real se ve luego en Apify Console → Billing/Usage)")
    if not args.si:
        respuesta = input("¿Lanzar la corrida en Apify? Esto consume crédito. [s/N] ")
        if respuesta.strip().lower() not in ("s", "si", "sí", "y", "yes"):
            print("Corrida cancelada. No se gastó nada.")
            return 0

    entrada = {
        "profiles": cuentas,
        "resultsPerPage": args.videos,
    }

    print("Llamando a Apify (puede tardar 1-3 minutos)...")
    try:
        items = correr_actor(ACTOR, entrada, token)
    except ApifyError as e:
        print(f"[error] {e}")
        return 1

    # Guardar el crudo tal cual: un archivo por corrida, nunca se sobreescribe.
    CARPETA_RAW.mkdir(parents=True, exist_ok=True)
    marca = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    ruta_salida = CARPETA_RAW / f"{marca}-raw.json"
    # encoding explícito: en Windows el default (cp1252) no soporta los emojis
    # que traen los captions de TikTok
    ruta_salida.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    print(f"[ok] {len(items)} items crudos guardados en {ruta_salida.relative_to(ROOT)}")

    # Normalizar al esquema interno y guardar el snapshot del día.
    fecha_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot = normalizar_items(items, fecha_iso)
    ruta_snapshot = guardar_snapshot(snapshot, fecha_iso[:10])

    print(f"[ok] snapshot normalizado: {ruta_snapshot.relative_to(ROOT)}")
    for cuenta in snapshot["accounts"]:
        print(f"  @{cuenta['handle']}: {cuenta['followers']:,} seguidores, "
              f"{len(cuenta['videos'])} videos")
    for error in snapshot["errors"]:
        print(f"  [aviso] {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
