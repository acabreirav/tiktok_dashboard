"""Tests del cliente Apify asíncrono, con requests y sleep mockeados
(no toca la red ni gasta crédito)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import apify_client
from apify_client import ApifyCreditError, ApifyError, correr_actor


def _resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def test_flujo_exitoso_dispara_pollea_y_lee_dataset():
    inicio = _resp({"data": {"id": "run1", "defaultDatasetId": "ds1", "status": "RUNNING"}}, 201)
    corriendo = _resp({"data": {"status": "RUNNING", "defaultDatasetId": "ds1"}})
    listo = _resp({"data": {"status": "SUCCEEDED", "defaultDatasetId": "ds1"}})
    items = _resp([{"a": 1}, {"a": 2}])

    with patch.object(apify_client, "time") as t, \
         patch("apify_client.requests.post", return_value=inicio) as post, \
         patch("apify_client.requests.get", side_effect=[corriendo, listo, items]) as get:
        t.time.side_effect = [0, 1, 2, 3, 4, 5]  # nunca supera el límite
        t.sleep.return_value = None
        resultado = correr_actor("x/y", {"in": 1}, "TOKEN",
                                 timeout_run_s=100, poll_cada_s=5)

    assert resultado == [{"a": 1}, {"a": 2}]
    # el run se inició con el timeout explícito
    assert post.call_args.kwargs["params"]["timeout"] == 100
    # se consultó estado 2 veces + 1 lectura de dataset
    assert get.call_count == 3


def test_estado_timed_out_levanta_error_con_dataset():
    inicio = _resp({"data": {"id": "run9", "defaultDatasetId": "ds9", "status": "RUNNING"}}, 201)
    timed = _resp({"data": {"status": "TIMED-OUT", "defaultDatasetId": "ds9"}})
    with patch.object(apify_client, "time") as t, \
         patch("apify_client.requests.post", return_value=inicio), \
         patch("apify_client.requests.get", return_value=timed):
        t.time.side_effect = [0, 1, 2, 3]
        t.sleep.return_value = None
        with pytest.raises(ApifyError) as exc:
            correr_actor("x/y", {}, "TOKEN", timeout_run_s=100, poll_cada_s=5)
    assert "TIMED-OUT" in str(exc.value) and "ds9" in str(exc.value)


def test_402_sin_credito_levanta_error_de_credito():
    # Apify rechaza el inicio con 402 + tipo not-enough-usage-to-run-paid-actor
    rechazo = _resp({"error": {"type": "not-enough-usage-to-run-paid-actor",
                               "message": "..."}}, status=402)
    rechazo.text = "not enough usage"
    with patch("apify_client.requests.post", return_value=rechazo):
        with pytest.raises(ApifyCreditError):
            correr_actor("x/y", {}, "TOKEN")
    # ApifyCreditError es un ApifyError: el caller puede atrapar ambos
    assert issubclass(ApifyCreditError, ApifyError)


def test_script_se_rinde_si_el_run_nunca_termina():
    inicio = _resp({"data": {"id": "runZ", "defaultDatasetId": "dsZ", "status": "RUNNING"}}, 201)
    corriendo = _resp({"data": {"status": "RUNNING", "defaultDatasetId": "dsZ"}})
    with patch.object(apify_client, "time") as t, \
         patch("apify_client.requests.post", return_value=inicio), \
         patch("apify_client.requests.get", return_value=corriendo):
        # el reloj salta más allá del límite (timeout_run_s + margen_s)
        t.time.side_effect = [0, 10_000, 20_000]
        t.sleep.return_value = None
        with pytest.raises(ApifyError) as exc:
            correr_actor("x/y", {}, "TOKEN", timeout_run_s=100, poll_cada_s=5, margen_s=50)
    assert "dejó de esperar" in str(exc.value)
