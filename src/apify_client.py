"""Wrapper delgado sobre la API HTTP de Apify — modo ASÍNCRONO con polling.

Antes usábamos el endpoint síncrono (run-sync-get-dataset-items), que fija un
timeout corto al run y devuelve todo de una. Con ~50 cuentas eso reventaba con
408 run-timeout-exceeded / estado TIMED-OUT. Ahora:

  1) se dispara el actor (con timeoutSecs EXPLÍCITO del run),
  2) se consulta el estado cada `poll_cada_s` hasta un estado terminal,
  3) recién con SUCCEEDED se leen los items del dataset.

Todos los tiempos son parámetros, no números mágicos.
"""

import time

import requests

API_BASE = "https://api.apify.com/v2"

# Estados en los que el run ya no cambia (Apify docs).
ESTADOS_TERMINALES = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}


class ApifyError(RuntimeError):
    """Error al hablar con Apify (token inválido, run fallido/colgado, etc.)."""


def correr_actor(
    actor: str,
    entrada: dict,
    token: str,
    *,
    timeout_run_s: int = 1800,
    poll_cada_s: int = 10,
    margen_s: int = 300,
) -> list:
    """Corre `actor` de forma asíncrona y devuelve los items del dataset.

    - `timeout_run_s`: cuánto se le permite correr al actor EN Apify (se pasa
      como `timeout` al iniciar el run; si se pasa, el run queda TIMED-OUT).
    - `poll_cada_s`: cada cuánto consultamos el estado.
    - `margen_s`: colchón que el script espera POR ENCIMA del timeout del run
      antes de rendirse (para cubrir el arranque/cola del run en Apify).
    """
    slug = actor.replace("/", "~")  # en la URL el actor va con ~ en vez de /

    # 1) Disparar el run -----------------------------------------------------
    try:
        r = requests.post(
            f"{API_BASE}/acts/{slug}/runs",
            params={"token": token, "timeout": timeout_run_s},
            json=entrada,
            timeout=60,
        )
    except requests.RequestException as e:
        raise ApifyError(f"No se pudo iniciar el actor {actor}: {e}") from e
    if r.status_code not in (200, 201):
        raise ApifyError(f"Apify rechazó el inicio ({r.status_code}): {r.text[:400]}")

    data = r.json()["data"]
    run_id = data["id"]
    dataset_id = data.get("defaultDatasetId")
    estado = data.get("status", "READY")

    # 2) Polling hasta estado terminal --------------------------------------
    limite = time.time() + timeout_run_s + margen_s
    while estado not in ESTADOS_TERMINALES:
        if time.time() > limite:
            raise ApifyError(
                f"El script dejó de esperar el run {run_id} tras "
                f"{timeout_run_s + margen_s}s (último estado: {estado}). "
                f"El run puede seguir vivo en la Console."
            )
        time.sleep(poll_cada_s)
        try:
            rr = requests.get(
                f"{API_BASE}/actor-runs/{run_id}",
                params={"token": token},
                timeout=60,
            )
            rr.raise_for_status()
        except requests.RequestException as e:
            raise ApifyError(f"No se pudo consultar el run {run_id}: {e}") from e
        d = rr.json()["data"]
        estado = d.get("status")
        dataset_id = d.get("defaultDatasetId", dataset_id)

    if estado != "SUCCEEDED":
        raise ApifyError(
            f"El run {run_id} terminó en estado {estado} (no SUCCEEDED). "
            f"Revísalo en la Console: si dejó items PARCIALES en el dataset "
            f"{dataset_id}, decide si rescatarlos o descartar la corrida."
        )

    # 3) Leer el dataset -----------------------------------------------------
    try:
        ri = requests.get(
            f"{API_BASE}/datasets/{dataset_id}/items",
            params={"token": token, "format": "json", "clean": "true"},
            timeout=120,
        )
        ri.raise_for_status()
    except requests.RequestException as e:
        raise ApifyError(f"No se pudo leer el dataset {dataset_id}: {e}") from e
    return ri.json()
