#!/usr/bin/env python3
"""Epic, Steam ve GOG'daki ücretsiz oyunları Discord kanalına bildirir."""

import argparse
import json
import os
import re
import sys
import time
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
    image: str = ""  # embed'de küçük kapak görseli / "" (yoksa)


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


def _game_key(store, title):
    """Tekrar bildirimini önleyen kimlik.

    Kaynaktan (Epic API / GamerPower) BAĞIMSIZ olmalı: aynı oyun bir kaynaktan
    düşüp diğerinde kalabiliyor. Kimlik kaynağa bağlı olsaydı bu durumda oyun
    yeni sanılıp tekrar bildirilirdi.
    """
    return f"{store.lower()}:{_normalize(title)}"


def _epic_image(element):
    """Kapak görseli. Dikey 'Thumbnail' embed'de en iyi duran seçenek;
    yoksa sırayla diğer tiplere düşer."""
    images = {image.get("type"): image.get("url")
              for image in (element.get("keyImages") or []) if image.get("url")}
    for kind in ("Thumbnail", "OfferImageTall", "OfferImageWide", "featuredMedia"):
        if images.get(kind):
            return images[kind]
    return ""


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
                    key=_game_key("Epic", element["title"]),
                    title=element["title"],
                    store="Epic",
                    url=f"https://store.epicgames.com/tr/p/{slug}",
                    worth=total.get("fmtPrice", {}).get("originalPrice", ""),
                    ends_at=end.isoformat(),
                    image=_epic_image(element),
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
        title = clean_gp_title(item["title"])
        games.append(Game(
            key=_game_key(store, title),
            title=title,
            store=store,
            url=item["open_giveaway_url"],
            worth="" if worth == "N/A" else worth,
            ends_at=ends_at,
            image=item.get("thumbnail", ""),
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


EMBED_LIMIT = 10          # Discord'un bir mesajdaki embed sınırı
CONTENT_LIMIT = 1900      # content sınırı 2000; pay bırakıyoruz
COLOR_FREE = 0x57F287     # Discord yeşili
STORE_ORDER = ["Epic", "Steam", "GOG"]


def game_embed(game):
    """Tek bir oyun için Discord embed'i üretir."""
    fields = []
    if game.worth:
        fields.append({"name": "Normal fiyatı", "value": game.worth, "inline": True})
    if game.ends_at:
        unix = int(datetime.fromisoformat(game.ends_at).timestamp())
        # <t:...:R> Discord'un göreli zaman etiketi: "3 gün içinde" diye
        # ve her kullanıcının kendi saat diliminde görünür.
        fields.append({"name": "Son tarih", "value": f"<t:{unix}:R>", "inline": True})
    embed = {
        "title": game.title,
        "url": game.url,
        "description": f"**{game.store}**",
        "color": COLOR_FREE,
        "fields": fields,
    }
    if game.image:
        embed["thumbnail"] = {"url": game.image}
    return embed


def new_games_payloads(games):
    """Yeni oyun bildirimini Discord'un embed sınırına göre mesajlara böler."""
    payloads = []
    for index in range(0, len(games), EMBED_LIMIT):
        chunk = games[index:index + EMBED_LIMIT]
        payload = {"embeds": [game_embed(game) for game in chunk]}
        if index == 0:
            adet = "Yeni ücretsiz oyun" if len(games) == 1 else f"{len(games)} yeni ücretsiz oyun"
            payload["content"] = f"🎁 **{adet}!**"
        payloads.append(payload)
    return payloads


def weekly_payloads(games):
    """Haftalık özet: mağazaya göre gruplanmış liste.

    Discord'un content sınırı 2000 karakter olduğu için liste uzunsa
    birden fazla mesaja bölünür; tek mesaja sığdırmaya çalışmak uzun
    haftalarda özetin tamamen reddedilmesine yol açar.
    """
    if not games:
        return [{"content": "📅 **Haftalık özet** — şu anda ücretsiz oyun yok."}]

    lines = ["📅 **Haftalık özet — şu anda ücretsiz olanlar**"]
    for store in STORE_ORDER:
        in_store = [game for game in games if game.store == store]
        if not in_store:
            continue
        lines.append(f"\n**{store}**")
        for game in in_store:
            suffix = ""
            if game.ends_at:
                unix = int(datetime.fromisoformat(game.ends_at).timestamp())
                suffix = f" — bitiş <t:{unix}:R>"
            lines.append(f"• [{game.title}](<{game.url}>){suffix}")

    payloads = []
    chunk = []
    size = 0
    for line in lines:
        if chunk and size + len(line) + 1 > CONTENT_LIMIT:
            payloads.append({"content": "\n".join(chunk)})
            chunk, size = [], 0
        chunk.append(line)
        size += len(line) + 1
    if chunk:
        payloads.append({"content": "\n".join(chunk)})
    return payloads


def post_discord(webhook, payload):
    """Webhook'a mesaj gönderir. Rate limit'te bir kez tekrar dener.

    Hata mesajlarında webhook URL'i ASLA yer almaz — Actions logları
    depoya erişimi olan herkes tarafından görülebilir.
    """
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook, data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT):
            return
    except urllib.error.HTTPError as error:
        if error.code != 429:
            raise RuntimeError(f"Discord webhook hatası: HTTP {error.code}") from None
        wait = min(float(error.headers.get("Retry-After", 5)), 60)
        print(f"Rate limit, {wait} saniye bekleniyor")
        time.sleep(wait)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT):
            return
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Discord webhook hatası: HTTP {error.code}") from None


WEEKLY_WEEKDAY = 0   # Pazartesi
WEEKLY_HOUR = 9      # TSİ


def is_weekly_time(now):
    """Haftalık özetin çıkacağı saat mi? Cron saat başı çalıştığı için
    bu pencere bir saatlik ve haftada tam bir kez yakalanır."""
    local = now.astimezone(TZ)
    return local.weekday() == WEEKLY_WEEKDAY and local.hour == WEEKLY_HOUR


def collect(now):
    """İki kaynağı çeker, birleştirir, tekilleştirir.

    Bir kaynak çökerse diğeriyle devam edilir. İkisi birden çökerse
    istisna fırlatılır — yoksa "hiç oyun yok" sanılıp durum dosyası
    yanlış güncellenir.
    """
    games = []
    failures = []

    try:
        games += parse_epic(fetch_json(EPIC_URL), now)
    except Exception as error:            # ağ, JSON veya şema değişikliği
        failures.append(f"Epic: {error}")

    try:
        payload = fetch_json(GAMERPOWER_URL)
        # Kampanya yokken GamerPower liste yerine {"status": 0, ...} döner
        if isinstance(payload, list):
            games += parse_gamerpower(payload, now)
    except Exception as error:
        failures.append(f"GamerPower: {error}")

    for failure in failures:
        print(f"UYARI: {failure}", file=sys.stderr)
    if len(failures) == 2:
        raise RuntimeError("Kaynakların hiçbirine ulaşılamadı")

    return dedupe(games)  # Epic önce eklendiği için çakışmada Epic kazanır


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ücretsiz oyunları Discord'a bildirir.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Discord'a göndermeden mesajları ekrana bas")
    parser.add_argument("--force-weekly", action="store_true",
                        help="Pazartesi beklemeden haftalık özeti üret")
    parser.add_argument("--self-test", action="store_true",
                        help="Ağ gerektirmeyen iç testleri çalıştır")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook and not args.dry_run:
        print("HATA: DISCORD_WEBHOOK_URL tanımlı değil", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    games = collect(now)

    seen = prune_seen(load_seen(SEEN_FILE), now)
    fresh = [game for game in games if game.key not in seen]

    payloads = list(new_games_payloads(fresh)) if fresh else []
    if args.force_weekly or is_weekly_time(now):
        payloads.extend(weekly_payloads(games))

    if not payloads:
        print("Yeni bir şey yok.")
        return 0

    if args.dry_run:
        for payload in payloads:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    # Gönderim başarısız olursa seen.json'a DOKUNULMAZ; bir sonraki
    # çalışma aynı oyunları tekrar dener.
    for payload in payloads:
        post_discord(webhook, payload)

    default_end = (now + timedelta(days=DEFAULT_KEEP_DAYS)).isoformat()
    for game in fresh:
        seen[game.key] = game.ends_at or default_end
    save_seen(SEEN_FILE, seen)

    print(f"{len(fresh)} yeni oyun bildirildi.")
    return 0


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
            "keyImages": [
                {"type": "OfferImageWide", "url": "https://cdn1.epicgames.com/wide.jpg"},
                {"type": "Thumbnail", "url": "https://cdn1.epicgames.com/thumb.jpg"},
            ],
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
    assert g.key == "epic:beaconpines", g.key
    assert g.worth == "₺149,00", g.worth
    assert g.ends_at == "2026-08-13T15:00:00+00:00", g.ends_at
    # Thumbnail, geniş görsele tercih edilmeli
    assert g.image == "https://cdn1.epicgames.com/thumb.jpg", g.image

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
    # keyImages hiç yoksa çökmemeli, görsel boş kalmalı
    assert parse_epic(fallback, now)[0].image == ""

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
         "status": "Active", "open_giveaway_url": "https://www.gamerpower.com/open/cat",
         "thumbnail": "https://www.gamerpower.com/offers/1/cat.jpg"},
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
    assert gp[0].key == "epic:catnamedmojave", gp[0].key
    assert gp[0].store == "Epic", gp[0].store
    assert gp[0].url == "https://www.gamerpower.com/open/cat"
    assert gp[0].worth == "$9.99"
    assert gp[0].ends_at == "2026-08-31T23:59:00+00:00", gp[0].ends_at
    assert gp[0].image == "https://www.gamerpower.com/offers/1/cat.jpg", gp[0].image
    assert gp[1].image == "", gp[1].image  # thumbnail alanı yoksa boş
    assert gp[1].store == "Steam"
    assert gp[1].worth == "", gp[1].worth      # "N/A" boşa çevrilir
    assert gp[1].ends_at == "", gp[1].ends_at  # "N/A" boşa çevrilir

    # --- kimlik kaynaktan bağımsız olmalı ---
    # Gerçek hata: Epic'in promosyon penceresi kapanınca oyun Epic verisinden
    # düştü ama GamerPower'da aktif kaldı; kimlik kaynağa bağlı olduğu için
    # aynı oyun "yeni" sanılıp tekrar bildirildi.
    epic_kayit = parse_epic(epic_payload, now)[0]
    ayni_oyun_gp = parse_gamerpower([{
        "id": 9999, "title": "Beacon Pines (Epic Games) Giveaway", "worth": "$19.99",
        "platforms": "PC, Epic Games Store", "end_date": "2026-08-14 23:59:00",
        "status": "Active", "open_giveaway_url": "https://www.gamerpower.com/open/bp",
    }], now)[0]
    assert epic_kayit.key == ayni_oyun_gp.key, (epic_kayit.key, ayni_oyun_gp.key)

    # Farklı mağazadaki aynı isimli oyun ayrı kimlik almalı
    farkli_magaza = parse_gamerpower([{
        "id": 8888, "title": "Beacon Pines (Steam) Giveaway", "worth": "$19.99",
        "platforms": "PC, Steam", "end_date": "2026-08-14 23:59:00",
        "status": "Active", "open_giveaway_url": "https://www.gamerpower.com/open/bp2",
    }], now)[0]
    assert farkli_magaza.key != epic_kayit.key

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

    # --- game_embed ---
    game = Game("epic:beacon-pines", "Beacon Pines", "Epic",
                "https://store.epicgames.com/tr/p/beacon-pines", "₺149,00",
                "2026-08-20T15:00:00+00:00", "https://cdn1.epicgames.com/thumb.jpg")
    emb = game_embed(game)
    assert emb["title"] == "Beacon Pines"
    assert emb["thumbnail"] == {"url": "https://cdn1.epicgames.com/thumb.jpg"}
    assert emb["url"] == game.url
    assert "Epic" in emb["description"]
    names = [f["name"] for f in emb["fields"]]
    assert names == ["Normal fiyatı", "Son tarih"], names
    # Discord zaman etiketi: <t:UNIX:R> biçiminde olmalı ki herkes kendi saatinde görsün
    assert emb["fields"][1]["value"] == "<t:1787238000:R>", emb["fields"][1]["value"]

    # Fiyat ve tarih bilinmiyorsa o alanlar hiç eklenmemeli
    bare = Game("gp:1", "Dwarven Realms", "Steam", "https://x", "", "")
    assert game_embed(bare)["fields"] == []
    # Görsel yoksa thumbnail anahtarı hiç eklenmemeli
    assert "thumbnail" not in game_embed(bare)

    # --- new_games_payloads: Discord bir mesajda en fazla 10 embed alır ---
    many = [Game(f"k{i}", f"Oyun {i}", "Epic", "https://x", "", "") for i in range(23)]
    payloads = new_games_payloads(many)
    assert [len(p["embeds"]) for p in payloads] == [10, 10, 3]
    assert "content" in payloads[0] and payloads[0]["content"]
    assert "content" not in payloads[1]  # başlık sadece ilk mesajda

    # --- weekly_payloads: mağazaya göre gruplanmış mesaj(lar) ---
    weekly = weekly_payloads([game, bare])
    assert len(weekly) == 1, len(weekly)
    text = weekly[0]["content"]
    assert "Epic" in text and "Steam" in text
    assert "Beacon Pines" in text and "Dwarven Realms" in text
    assert text.index("Epic") < text.index("Steam")

    # Hiç oyun yoksa da anlamlı bir mesaj çıkmalı
    assert weekly_payloads([])[0]["content"]

    # Uzun liste Discord'un 2000 karakterlik content sınırına bölünmeli
    lots = [Game(f"k{i}", f"Oldukça Uzun Bir Oyun Adı Numara {i}", "Epic",
                 f"https://store.epicgames.com/tr/p/oldukca-uzun-bir-oyun-adi-{i}", "", "")
            for i in range(60)]
    parts = weekly_payloads(lots)
    assert len(parts) > 1, len(parts)
    assert all(len(p["content"]) <= 2000 for p in parts), [len(p["content"]) for p in parts]
    # Bölünme sırasında hiçbir oyun düşmemeli
    birlesik = "\n".join(p["content"] for p in parts)
    assert all(f"Numara {i}]" in birlesik for i in range(60))

    # --- is_weekly_time: Pazartesi 09:00 TSİ (= 06:00 UTC) ---
    # Cron saat başı çalışır, bu yüzden pencere tam bir saat genişliğinde.
    assert is_weekly_time(datetime(2026, 8, 17, 6, 5, tzinfo=timezone.utc))    # Pzt 09:05 TSİ
    assert not is_weekly_time(datetime(2026, 8, 17, 7, 5, tzinfo=timezone.utc))  # Pzt 10:05
    assert not is_weekly_time(datetime(2026, 8, 18, 6, 5, tzinfo=timezone.utc))  # Salı

    print("self-test: TAMAM")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
