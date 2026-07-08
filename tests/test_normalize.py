"""Tests del normalizador con items de ejemplo que imitan la salida real
del actor clockworks/tiktok-profile-scraper (corrida del 2026-07-07)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from normalize import normalizar_ig, normalizar_items


def item_crudo(handle="cuenta.demo", video_id="v1", fans=1000, **extra):
    """Fábrica de items crudos con la forma real del actor."""
    base = {
        "id": video_id,
        "text": "caption de prueba 🐘",
        "createTimeISO": "2026-07-05T14:00:08.000Z",
        "playCount": 4500, "diggCount": 480,
        "commentCount": 56, "shareCount": 32,
        "authorMeta": {
            "name": handle, "fans": fans, "following": 80,
            "heart": 26000, "video": 13, "verified": True,
        },
        "input": handle,
    }
    base.update(extra)
    return base


def test_agrupa_videos_por_cuenta():
    items = [
        item_crudo("ana", "v1"), item_crudo("ana", "v2"),
        item_crudo("beto", "v3", fans=555),
    ]
    snap = normalizar_items(items, "2026-07-07T00:00Z")

    assert snap["date"] == "2026-07-07T00:00Z"
    assert len(snap["accounts"]) == 2
    ana = next(c for c in snap["accounts"] if c["handle"] == "ana")
    assert [v["id"] for v in ana["videos"]] == ["v1", "v2"]


def test_mapea_campos_del_actor_al_esquema_interno():
    snap = normalizar_items([item_crudo()], "2026-07-07T00:00Z")
    cuenta = snap["accounts"][0]

    # perfil: fans→followers, heart→likesTotal, video→videoCount
    assert cuenta["followers"] == 1000
    assert cuenta["likesTotal"] == 26000
    assert cuenta["videoCount"] == 13
    assert cuenta["verified"] is True

    # video: playCount→views, diggCount→likes, etc.
    video = cuenta["videos"][0]
    assert video["views"] == 4500
    assert video["likes"] == 480
    assert video["comments"] == 56
    assert video["shares"] == 32
    assert video["postedAt"] == "2026-07-05T14:00:08.000Z"
    assert video["caption"] == "caption de prueba 🐘"


def test_normalizar_ig_mapea_campos_del_actor():
    items = [{
        "username": "cuenta.demo", "followersCount": 45000,
        "followsCount": 300, "postsCount": 120, "verified": True,
    }]
    snap = normalizar_ig(items, "2026-07-08T00:00Z")
    perfil = snap["profiles"][0]
    assert perfil["handle"] == "cuenta.demo"
    assert perfil["followers"] == 45000
    assert perfil["posts"] == 120
    assert perfil["verified"] is True
    assert snap["errors"] == []


def test_normalizar_ig_registra_errores_sin_abortar():
    items = [
        {"username": "ok", "followersCount": 10},
        {"inputUrl": "https://instagram.com/borrada", "error": "not found"},
    ]
    snap = normalizar_ig(items, "2026-07-08T00:00Z")
    assert len(snap["profiles"]) == 1
    assert len(snap["errors"]) == 1
    assert "borrada" in snap["errors"][0]


def test_item_con_error_no_aborta_y_queda_registrado():
    # una cuenta privada/borrada viene sin authorMeta: se registra y se sigue
    items = [
        item_crudo("ana", "v1"),
        {"input": "cuenta.borrada", "error": "not found", "authorMeta": None},
    ]
    snap = normalizar_items(items, "2026-07-07T00:00Z")

    assert len(snap["accounts"]) == 1
    assert len(snap["errors"]) == 1
    assert "cuenta.borrada" in snap["errors"][0]
