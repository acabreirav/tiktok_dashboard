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
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from apify_client import ApifyCreditError, ApifyError, correr_actor
from normalize import guardar_snapshot, normalizar_ig, normalizar_items


def avisar_resumen(linea: str) -> None:
    """Deja un aviso destacado en el resumen del run de GitHub Actions.

    Escribe en $GITHUB_STEP_SUMMARY si existe (aparece en la UI del run);
    en local es no-op. Así una corrida incompleta no pasa desapercibida."""
    ruta = os.getenv("GITHUB_STEP_SUMMARY")
    if ruta:
        try:
            with open(ruta, "a", encoding="utf-8") as f:
                f.write(linea + "\n")
        except OSError:
            pass

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
    parser.add_argument("--solo-ig", action="store_true",
                        help="solo perfiles de Instagram, sin corrida TikTok "
                             "(útil para tomar la primera foto IG sin costo extra)")
    parser.add_argument("--timeout-run", type=int, default=1800,
                        help="segundos que se le permite correr a CADA actor en "
                             "Apify (default 1800 = 30 min)")
    parser.add_argument("--poll", type=int, default=10,
                        help="cada cuántos segundos se consulta el estado del run "
                             "(default 10)")
    args = parser.parse_args()

    # Token desde .env (local). En GitHub Actions vendrá como variable de entorno.
    load_dotenv(ROOT / ".env")
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
    resultados_estimados = 0 if args.solo_ig else len(cuentas) * (1 + args.videos)
    print("Plan de la corrida:")
    if not args.solo_ig:
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

    CARPETA_RAW.mkdir(parents=True, exist_ok=True)
    marca = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    fecha_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    opciones_run = {"timeout_run_s": args.timeout_run, "poll_cada_s": args.poll}

    # Cada red es un run INDEPENDIENTE: guarda su snapshot apenas termina y una
    # falla no tumba a la otra. El código de salida refleja solo TikTok (la red
    # prioritaria); IG es complementaria.
    exito_tiktok = True

    if not args.solo_ig:
        try:
            print(f"TikTok: disparando {len(cuentas)} cuentas "
                  f"(timeout run {args.timeout_run}s, polling cada {args.poll}s)...")
            items = correr_actor(ACTOR, {"profiles": cuentas, "resultsPerPage": args.videos},
                                 token, **opciones_run)
            # crudo tal cual (encoding explícito: Windows usa cp1252 y los
            # captions de TikTok traen emojis)
            (CARPETA_RAW / f"{marca}-raw.json").write_text(
                json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            snapshot = normalizar_items(items, fecha_iso)
            ruta_snapshot = guardar_snapshot(snapshot, fecha_iso[:10])
            # GUARDA DE COMPLETITUD: dejar constancia explícita de pedidas/traídas.
            traidas = len(snapshot["accounts"])
            print(f"[ok] snapshot TikTok: {ruta_snapshot.relative_to(ROOT)}")
            print(f"  cuentas pedidas: {len(cuentas)} / traídas: {traidas}")
            for error in snapshot["errors"]:
                print(f"  [aviso] {error}")
            if traidas < len(cuentas):
                faltan = len(cuentas) - traidas
                # ::error:: crea una anotación roja en el run; el exit≠0 hace fallar
                # el job → el workflow NO commitea el snapshot cojo en verde.
                print(f"::error::TikTok INCOMPLETO: {traidas}/{len(cuentas)} cuentas "
                      f"({faltan} faltan). Un snapshot parcial es un hueco irrecuperable "
                      f"en la serie — no se da por bueno. Causa típica: crédito Apify "
                      f"agotado a mitad del run. Revisa saldo y relanza.")
                avisar_resumen(f"❌ **TikTok incompleto:** {traidas}/{len(cuentas)} cuentas "
                               f"({faltan} faltan). Snapshot NO commiteado.")
                exito_tiktok = False
            else:
                avisar_resumen(f"✅ **TikTok completo:** {traidas}/{len(cuentas)} cuentas.")
        except ApifyCreditError as e:
            print(f"::error::sin crédito Apify — corrida TikTok omitida ({e})")
            avisar_resumen("❌ **TikTok omitido: sin crédito Apify.** Recarga saldo y relanza.")
            exito_tiktok = False
        except (ApifyError, OSError) as e:
            print(f"[error TikTok] {e}")
            avisar_resumen(f"❌ **TikTok falló:** {e}")
            exito_tiktok = False

    # --- Instagram (solo perfil) — run aparte; si falla, no afecta a TikTok ---
    if cuentas_ig:
        try:
            print(f"\nInstagram: disparando {len(cuentas_ig)} perfiles...")
            items_ig = correr_actor(ACTOR_IG, {"usernames": cuentas_ig},
                                    token, **opciones_run)
            (CARPETA_RAW / f"{marca}-ig-raw.json").write_text(
                json.dumps(items_ig, ensure_ascii=False, indent=2), encoding="utf-8")
            snap_ig = normalizar_ig(items_ig, fecha_iso)
            ruta_ig = guardar_snapshot(snap_ig, fecha_iso[:10], carpeta=CARPETA_IG)
            traidas_ig = len(snap_ig["profiles"])
            print(f"[ok] snapshot Instagram: {ruta_ig.relative_to(ROOT)}")
            print(f"  perfiles pedidos: {len(cuentas_ig)} / traídos: {traidas_ig}")
            for error in snap_ig["errors"]:
                print(f"  [aviso IG] {error}")
            # IG es complementaria: su incompletitud avisa pero NO tumba el job.
            if traidas_ig < len(cuentas_ig):
                faltan = len(cuentas_ig) - traidas_ig
                print(f"::warning::Instagram INCOMPLETO: {traidas_ig}/{len(cuentas_ig)} "
                      f"perfiles ({faltan} faltan).")
                avisar_resumen(f"⚠️ **Instagram incompleto:** {traidas_ig}/{len(cuentas_ig)} perfiles.")
            else:
                avisar_resumen(f"✅ **Instagram completo:** {traidas_ig}/{len(cuentas_ig)} perfiles.")
        except ApifyCreditError as e:
            print(f"::warning::sin crédito Apify — corrida Instagram omitida ({e})")
            avisar_resumen("⚠️ **Instagram omitido: sin crédito Apify.**")
        except (ApifyError, OSError) as e:
            print(f"::warning::la corrida de Instagram falló y se omite: {e}")
            avisar_resumen(f"⚠️ **Instagram falló:** {e}")

    return 0 if exito_tiktok else 1


if __name__ == "__main__":
    sys.exit(main())
