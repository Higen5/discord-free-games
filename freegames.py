#!/usr/bin/env python3
"""Epic, Steam ve GOG'daki ücretsiz oyunları Discord kanalına bildirir."""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=3))  # TSİ

EPIC_URL = ("https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
            "?locale=tr-TR&country=TR&allowCountries=TR")
GAMERPOWER_URL = "https://www.gamerpower.com/api/giveaways?type=game"

# GamerPower'ın "platforms" alanındaki isim -> bizim mağaza etiketimiz.
# Yeni mağaza eklemek için buraya bir satır yeter.
STORES = {"Epic Games Store": "Epic", "Steam": "Steam", "GOG": "GOG"}

TIMEOUT = 20
USER_AGENT = "discord-free-games/1.0 (+https://github.com/Higen5/discord-free-games)"


@dataclass
class Game:
    key: str        # tekrar bildirimini önleyen kalıcı kimlik
    title: str
    store: str
    url: str
    worth: str      # "₺149,00" / "$9.99" / "" (bilinmiyorsa)
    ends_at: str    # ISO 8601 UTC / "" (süresizse)


def fetch_json(url):
    """URL'den JSON çeker. Hata durumunda istisna fırlatır."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _iso(value):
    """Epic'in '...Z' formatını timezone-aware datetime'a çevirir."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _epic_slug(element):
    """productSlug çoğu girdide null gelir; sırayla yedeklere düşer."""
    candidates = list(element.get("offerMappings") or [])
    candidates += (element.get("catalogNs") or {}).get("mappings") or []
    for mapping in candidates:
        if mapping.get("pageSlug"):
            return mapping["pageSlug"]
    return element.get("productSlug") or element.get("urlSlug") or ""


def parse_epic(payload, now):
    """Epic yanıtından ŞU AN ücretsiz olan oyunları çıkarır.

    Üç şart birden aranır: promosyon aktif listede olmalı, indirim sonrası
    yüzde 0 olmalı ve şu an promosyon penceresinin içinde olunmalı. Üçüncü
    şart olmazsa henüz başlamamış kampanyalar "bedava" diye duyurulur.
    """
    games = []
    elements = payload["data"]["Catalog"]["searchStore"]["elements"]
    for element in elements:
        total = element.get("price", {}).get("totalPrice", {})
        if total.get("originalPrice", 0) <= 0:
            continue  # zaten kalıcı olarak ücretsiz, promosyon değil
        promotions = element.get("promotions") or {}
        for group in promotions.get("promotionalOffers") or []:
            for offer in group.get("promotionalOffers") or []:
                if offer.get("discountSetting", {}).get("discountPercentage") != 0:
                    continue
                start = _iso(offer["startDate"])
                end = _iso(offer["endDate"])
                if not (start <= now < end):
                    continue
                slug = _epic_slug(element)
                games.append(Game(
                    key=f"epic:{slug}",
                    title=element["title"],
                    store="Epic",
                    url=f"https://store.epicgames.com/tr/p/{slug}",
                    worth=total.get("fmtPrice", {}).get("originalPrice", ""),
                    ends_at=end.isoformat(),
                ))
    return games


def clean_gp_title(raw):
    """'Cat Named Mojave (Epic Games) Giveaway' -> 'Cat Named Mojave'"""
    title = re.sub(r"\s*\([^)]*\)\s*", " ", raw)
    title = re.sub(r"\s*Giveaway\s*$", "", title.strip(), flags=re.IGNORECASE)
    return title.strip()


def parse_gamerpower(items, now):
    """GamerPower listesinden kapsanan mağazalardaki aktif kampanyaları çıkarır."""
    games = []
    for item in items:
        if item.get("status") != "Active":
            continue
        platforms = item.get("platforms", "")
        store = next((label for name, label in STORES.items() if name in platforms), None)
        if store is None:
            continue  # Itch.io, IndieGala, Ubisoft, mobil vs. kapsam dışı
        raw_end = item.get("end_date", "")
        ends_at = ""
        if raw_end and raw_end != "N/A":
            end = datetime.fromisoformat(raw_end).replace(tzinfo=timezone.utc)
            if end <= now:
                continue  # süresi dolmuş, status alanı geç güncellenmiş olabilir
            ends_at = end.isoformat()
        worth = item.get("worth", "")
        games.append(Game(
            key=f"gp:{item['id']}",
            title=clean_gp_title(item["title"]),
            store=store,
            url=item["open_giveaway_url"],
            worth="" if worth == "N/A" else worth,
            ends_at=ends_at,
        ))
    return games


SEEN_FILE = "seen.json"
DEFAULT_KEEP_DAYS = 90


def _normalize(title):
    """Başlıkları karşılaştırmak için harf/rakam dışındaki her şeyi atar."""
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def dedupe(games):
    """Aynı oyunun iki kaynaktan gelen kopyalarını teke indirir.

    Listede önce gelen kazanır; çağıran Epic'i başa koyar çünkü Epic'in
    kendi verisindeki tarihler kesin.
    """
    best = {}
    for game in games:
        best.setdefault(_normalize(game.title), game)
    return list(best.values())


def load_seen(path):
    """Bildirilmiş oyunları okur. Dosya yoksa veya bozuksa boş sözlük döner."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def prune_seen(seen, now):
    """Bitiş tarihi geçmiş kayıtları atar.

    Böylece aynı oyun aylar sonra tekrar bedava olursa yeniden bildirilir.
    """
    stamp = now.isoformat()
    return {key: end for key, end in seen.items() if end > stamp}


def save_seen(path, seen):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(seen, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _self_test():
    now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)

    # --- parse_epic ---
    # Üç girdi: (1) şu an bedava, (2) yüzdesi 0 ama promosyonu başlamamış,
    # (3) indirimli ama bedava değil. Sadece birincisi dönmeli.
    epic_payload = {"data": {"Catalog": {"searchStore": {"elements": [
        {
            "title": "Beacon Pines",
            "productSlug": None,
            "offerMappings": [{"pageSlug": "beacon-pines-629fc3"}],
            "catalogNs": {"mappings": [{"pageSlug": "beacon-pines-629fc3"}]},
            "price": {"totalPrice": {"originalPrice": 14900, "discountPrice": 0,
                                     "fmtPrice": {"originalPrice": "₺149,00"}}},
            "promotions": {"promotionalOffers": [{"promotionalOffers": [{
                "startDate": "2026-08-06T15:00:00.000Z",
                "endDate": "2026-08-13T15:00:00.000Z",
                "discountSetting": {"discountPercentage": 0},
            }]}], "upcomingPromotionalOffers": []},
        },
        {
            "title": "Caravan SandWitch",
            "productSlug": "caravan-sandwitch",
            "offerMappings": [],
            "catalogNs": {"mappings": []},
            "price": {"totalPrice": {"originalPrice": 41000, "discountPrice": 41000,
                                     "fmtPrice": {"originalPrice": "₺410,00"}}},
            "promotions": {"promotionalOffers": [], "upcomingPromotionalOffers": [
                {"promotionalOffers": [{
                    "startDate": "2026-08-13T15:00:00.000Z",
                    "endDate": "2026-08-20T15:00:00.000Z",
                    "discountSetting": {"discountPercentage": 0},
                }]}]},
        },
        {
            "title": "Ghostrunner 2",
            "productSlug": "ghostrunner-2",
            "offerMappings": [],
            "catalogNs": {"mappings": []},
            "price": {"totalPrice": {"originalPrice": 67999, "discountPrice": 54399,
                                     "fmtPrice": {"originalPrice": "₺679,99"}}},
            "promotions": {"promotionalOffers": [{"promotionalOffers": [{
                "startDate": "2026-08-10T15:00:00.000Z",
                "endDate": "2026-08-24T15:00:00.000Z",
                "discountSetting": {"discountPercentage": 20},
            }]}], "upcomingPromotionalOffers": []},
        },
    ]}}}}

    games = parse_epic(epic_payload, now)
    assert [g.title for g in games] == ["Beacon Pines"], [g.title for g in games]
    g = games[0]
    assert g.store == "Epic", g.store
    assert g.url == "https://store.epicgames.com/tr/p/beacon-pines-629fc3", g.url
    assert g.key == "epic:beacon-pines-629fc3", g.key
    assert g.worth == "₺149,00", g.worth
    assert g.ends_at == "2026-08-13T15:00:00+00:00", g.ends_at

    # productSlug null geldiğinde offerMappings'ten slug alınmalı (yukarıda doğrulandı).
    # Hiçbiri yoksa urlSlug'a düşmeli:
    fallback = {"data": {"Catalog": {"searchStore": {"elements": [{
        "title": "Yedek Slug", "productSlug": None, "offerMappings": [],
        "catalogNs": {"mappings": []}, "urlSlug": "yedek-slug",
        "price": {"totalPrice": {"originalPrice": 100, "discountPrice": 0,
                                 "fmtPrice": {"originalPrice": "₺1,00"}}},
        "promotions": {"promotionalOffers": [{"promotionalOffers": [{
            "startDate": "2026-08-06T15:00:00.000Z",
            "endDate": "2026-08-20T15:00:00.000Z",
            "discountSetting": {"discountPercentage": 0}}]}]},
    }]}}}}
    assert parse_epic(fallback, now)[0].url.endswith("/yedek-slug")

    # Promosyonu olmayan / fiyatı zaten 0 olan (free-to-play) girdi elenmeli
    f2p = {"data": {"Catalog": {"searchStore": {"elements": [{
        "title": "Zaten Bedava", "productSlug": "zaten-bedava", "offerMappings": [],
        "catalogNs": {"mappings": []},
        "price": {"totalPrice": {"originalPrice": 0, "discountPrice": 0,
                                 "fmtPrice": {"originalPrice": "0"}}},
        "promotions": {"promotionalOffers": [{"promotionalOffers": [{
            "startDate": "2026-08-06T15:00:00.000Z",
            "endDate": "2026-08-20T15:00:00.000Z",
            "discountSetting": {"discountPercentage": 0}}]}]},
    }]}}}}
    assert parse_epic(f2p, now) == []

    # promotions alanı null gelen girdi çökmemeli
    nullpromo = {"data": {"Catalog": {"searchStore": {"elements": [{
        "title": "Promosyonsuz", "productSlug": "yok", "offerMappings": [],
        "catalogNs": {"mappings": []},
        "price": {"totalPrice": {"originalPrice": 100, "discountPrice": 100,
                                 "fmtPrice": {"originalPrice": "₺1,00"}}},
        "promotions": None,
    }]}}}}
    assert parse_epic(nullpromo, now) == []

    # --- clean_gp_title ---
    assert clean_gp_title("Cat Named Mojave (Epic Games) Giveaway") == "Cat Named Mojave"
    assert clean_gp_title("Targeted – 10 Days (Epic Games) Giveaway") == "Targeted – 10 Days"
    assert clean_gp_title("Dora Diginoid: Metroidvania sci-fi adventure game") == \
        "Dora Diginoid: Metroidvania sci-fi adventure game"

    # --- parse_gamerpower ---
    gp_items = [
        {"id": 3742, "title": "Cat Named Mojave (Epic Games) Giveaway", "worth": "$9.99",
         "platforms": "PC, Epic Games Store", "end_date": "2026-08-31 23:59:00",
         "status": "Active", "open_giveaway_url": "https://www.gamerpower.com/open/cat"},
        {"id": 3700, "title": "Dwarven Realms (Steam) Giveaway", "worth": "N/A",
         "platforms": "PC, Steam", "end_date": "N/A", "status": "Active",
         "open_giveaway_url": "https://www.gamerpower.com/open/dwarven"},
        {"id": 3650, "title": "Eski Kampanya (Steam) Giveaway", "worth": "$1.00",
         "platforms": "PC, Steam", "end_date": "2026-08-01 12:00:00", "status": "Active",
         "open_giveaway_url": "https://www.gamerpower.com/open/eski"},
        {"id": 3601, "title": "NIGHTBELL (Itch.io) Giveaway", "worth": "$2.00",
         "platforms": "PC, Itch.io, DRM-Free", "end_date": "N/A", "status": "Active",
         "open_giveaway_url": "https://www.gamerpower.com/open/nightbell"},
        {"id": 3500, "title": "Bitmis (GOG) Giveaway", "worth": "$3.00",
         "platforms": "PC, GOG", "end_date": "2026-12-01 00:00:00", "status": "Expired",
         "open_giveaway_url": "https://www.gamerpower.com/open/bitmis"},
    ]
    gp = parse_gamerpower(gp_items, now)
    titles = [g.title for g in gp]
    # Itch.io kapsam dışı, Expired elenir, bitiş tarihi geçmiş olan elenir
    assert titles == ["Cat Named Mojave", "Dwarven Realms"], titles
    assert gp[0].key == "gp:3742", gp[0].key
    assert gp[0].store == "Epic", gp[0].store
    assert gp[0].url == "https://www.gamerpower.com/open/cat"
    assert gp[0].worth == "$9.99"
    assert gp[0].ends_at == "2026-08-31T23:59:00+00:00", gp[0].ends_at
    assert gp[1].store == "Steam"
    assert gp[1].worth == "", gp[1].worth      # "N/A" boşa çevrilir
    assert gp[1].ends_at == "", gp[1].ends_at  # "N/A" boşa çevrilir

    # --- dedupe ---
    a = Game("epic:beacon-pines", "Beacon Pines", "Epic",
             "https://store.epicgames.com/tr/p/beacon-pines", "₺149,00", "")
    b = Game("gp:999", "beacon pines!", "Epic",
             "https://www.gamerpower.com/open/beacon", "$14.99", "")
    c = Game("gp:1000", "Dwarven Realms", "Steam",
             "https://www.gamerpower.com/open/dwarven", "", "")
    merged = dedupe([a, b, c])
    assert [g.key for g in merged] == ["epic:beacon-pines", "gp:1000"], [g.key for g in merged]

    # --- prune_seen ---
    seen = {
        "epic:eski": "2026-08-01T00:00:00+00:00",   # süresi dolmuş, silinmeli
        "epic:yeni": "2026-09-01T00:00:00+00:00",   # sürüyor, kalmalı
    }
    pruned = prune_seen(seen, now)
    assert set(pruned) == {"epic:yeni"}, pruned

    # Bitiş tarihi tam şimdi olan kayıt silinmeli (sınır durumu)
    assert prune_seen({"k": now.isoformat()}, now) == {}

    print("self-test: TAMAM")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
