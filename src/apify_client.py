"""Wrapper delgado sobre la API HTTP de Apify.

Una sola función: correr un actor de forma síncrona y devolver los items
que produjo. Sin dependencias del SDK oficial — solo `requests`, para
mantener el proyecto simple y el comportamiento a la vista.
"""

import requests

API_BASE = "https://api.apify.com/v2"


class ApifyError(RuntimeError):
    """Error al hablar con Apify (token inválido, actor caído, etc.)."""


def correr_actor(actor: str, entrada: dict, token: str, timeout_s: int = 300) -> list:
    """Corre `actor` (ej. "clockworks/tiktok-profile-scraper") y espera el resultado.

    Usa el endpoint run-sync-get-dataset-items: lanza la corrida, espera a que
    termine y devuelve directamente la lista de items del dataset.
    """
    # En la URL de la API el actor se escribe con ~ en vez de /
    url = f"{API_BASE}/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items"
    try:
        respuesta = requests.post(
            url,
            params={"token": token, "timeout": timeout_s},
            json=entrada,
            timeout=timeout_s + 60,
        )
    except requests.RequestException as e:
        raise ApifyError(f"No se pudo conectar con Apify: {e}") from e

    if respuesta.status_code not in (200, 201):
        raise ApifyError(
            f"Apify respondió {respuesta.status_code}: {respuesta.text[:500]}"
        )
    return respuesta.json()
