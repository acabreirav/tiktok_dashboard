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
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from apify_client import ApifyError, correr_actor
from normalize import guardar_snapshot, normalizar_ig, normalizar_items

ROOT = Path(__file__).resolve().parent.parent
RUTA_LEGISLADORES = ROOT / "config" / "legisladores.csv"
CARPETA_RAW = ROOT / "data" / "snapshots" / "raw"
CARPETA_IG = ROOT / "data" / "snapshots" / "instagram"

# Actor elegido como primer candidato (ver CLAUDE.md §6): devuelve perfil
# y videos recientes en una sola corrida. Si el test muestra mala salida
# o costo alto, probamos apidojo/tiktok-scraper.
ACTOR = "clockworks/tiktok-profile-scraper"

# Instagram: SOLO PERFIL (seguidores/posts), sin scraping de contenido.
# Completa el diagnóstico de presencia digital a costo mínimo.
ACTOR_IG = "apify/instagram-profile-scraper"

# Tope duro para proteger la cuota de Apify (ver CLAUDE.md §12, Fase 7):
# el fetch se niega a correr si hay más cuentas activas que esto.
# Subido 30→60 el 2026-07-08 al ampliar a RM completa (decisión de Álvaro
# de costear el crédito extra; ~40 cuentas semanales ≈ $4.5-5/mes).
MAX_CUENTAS = 60


def cargar_cuentas() -> list[str]:
    """Handles con scrape=si en config/legisladores.csv (la fuente de verdad).

    "sin cuenta" es un dato válido de la base: significa que el legislador
    no tiene TikTok verificado, y por definición no se scrapea.
    """
    with open(RUTA_LEGISLADORES, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    return [
        f["handle_tiktok"].strip()
        for f in filas
        if f["scrape"].strip().lower() == "si"
        and f["handle_tiktok"].strip() not in ("", "sin cuenta")
    ]


def cargar_cuentas_ig() -> list[str]:
    """Handles de Instagram con valor en el CSV. Independiente del flag
    `scrape` (que gobierna TikTok): un legislador sin TikTok puede tener IG."""
    with open(RUTA_LEGISLADORES, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    return [
        h for f in filas
        if (h := f.get("handle_instagram", "").strip()) not in ("", "sin cuenta")
    ]


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
    if len(cuentas) > MAX_CUENTAS:
        print(f"[error] Hay {len(cuentas)} cuentas con scrape=si; el tope de "
              f"protección de cuota es {MAX_CUENTAS}. Revisa config/legisladores.csv "
              f"o sube MAX_CUENTAS en src/fetch.py de forma consciente.")
        return 1

    cuentas_ig = cargar_cuentas_ig()

    # --- Guarda de costo: mostrar el plan y confirmar antes de gastar ---
    resultados_estimados = len(cuentas) * (1 + args.videos)
    print("Plan de la corrida:")
    print(f"  actor:    {ACTOR}")
    print(f"  cuentas:  {len(cuentas)} ({', '.join(cuentas)})")
    print(f"  videos:   hasta {args.videos} por cuenta")
    if cuentas_ig:
        print(f"  instagram (solo perfil): {len(cuentas_ig)} cuentas via {ACTOR_IG}")
    print(f"  items estimados: ~{resultados_estimados} TikTok + {len(cuentas_ig)} IG "
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

    # --- Instagram (solo perfil) — si falla, NO tumba la corrida TikTok ---
    if cuentas_ig:
        try:
            print(f"\nInstagram: pidiendo {len(cuentas_ig)} perfiles...")
            items_ig = correr_actor(ACTOR_IG, {"usernames": cuentas_ig}, token)
            ruta_ig_raw = CARPETA_RAW / f"{marca}-ig-raw.json"
            ruta_ig_raw.write_text(json.dumps(items_ig, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
            snap_ig = normalizar_ig(items_ig, fecha_iso)
            ruta_ig = guardar_snapshot(snap_ig, fecha_iso[:10], carpeta=CARPETA_IG)
            print(f"[ok] snapshot Instagram: {ruta_ig.relative_to(ROOT)} "
                  f"({len(snap_ig['profiles'])} perfiles)")
            for error in snap_ig["errors"]:
                print(f"  [aviso IG] {error}")
        except (ApifyError, OSError) as e:
            print(f"[aviso IG] la corrida de Instagram falló y se omite: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
