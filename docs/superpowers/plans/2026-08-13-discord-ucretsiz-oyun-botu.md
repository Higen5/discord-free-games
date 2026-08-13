# Discord Ücretsiz Oyun Botu — Implementasyon Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Epic, Steam ve GOG'daki ücretsiz oyunları saatlik olarak takip edip Discord kanalına bildirim düşen, GitHub Actions üzerinde çalışan bir script.

**Architecture:** Tek Python dosyası, üçüncü parti bağımlılık yok. İki HTTP kaynağı çekilir, birleştirilip tekilleştirilir, `seen.json`'da olmayanlar "yeni" sayılıp Discord webhook'una gönderilir. Pazartesi sabahı ayrıca haftalık özet çıkar. Durum dosyası her çalışmada repoya geri commit edilir.

**Tech Stack:** Python 3 (yalnızca stdlib: `urllib`, `json`, `re`, `argparse`, `dataclasses`, `datetime`), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-13-discord-ucretsiz-oyun-botu-design.md`

## Global Constraints

- **Sıfır üçüncü parti bağımlılık.** `requirements.txt` yok, `pip install` yok. Sadece stdlib.
- **Tek kaynak dosyası:** `freegames.py`. Modüllere bölünmeyecek — proje bunu hak edecek büyüklükte değil.
- **Test framework yok.** Testler `freegames.py` içinde `_self_test()` fonksiyonunda `assert` ile yazılır, `--self-test` bayrağıyla çalışır, ağ erişimi gerektirmez.
- **Webhook URL'i asla loglanmaz, asla commit edilmez.** Hata mesajlarında URL basılmayacak; sadece HTTP durum kodu. `.env` `.gitignore`'da.
- **Discord mesajları Türkçe.**
- **Zaman dilimi:** Haftalık özetin zamanlaması TSİ'ye (UTC+3) göre hesaplanır. Karşılaştırmalar timezone-aware `datetime` ile yapılır; naive datetime kullanılmayacak.
- **Lokal geliştirme Windows'ta:** `python` değil **`py`** komutu kullanılır (`python` Microsoft Store stub'una gidiyor). Türkçe karakter ve `₺` basarken konsol cp1252'de patladığı için lokal çalıştırmalarda `PYTHONIOENCODING=utf-8` gerekir. GitHub Actions'ta (Linux) bu sorun yok, orada `python3`.
- **Ağ çağrılarında 20 saniye timeout.**

---

### Task 1: Kaynakları çekme ve ayrıştırma

Epic ve GamerPower yanıtlarını `Game` nesnelerine dönüştüren saf fonksiyonlar. Bu task ağ çağrısı yapan yardımcıyı da içerir ama testler sabit örnek veriyle çalışır.

**Files:**
- Create: `freegames.py`
- Create: `.gitignore` (zaten var, dokunma)

**Interfaces:**
- Consumes: yok (ilk task)
- Produces:
  - `@dataclass Game` alanları: `key: str`, `title: str`, `store: str`, `url: str`, `worth: str`, `ends_at: str` (ISO 8601 veya boş string)
  - `parse_epic(payload: dict, now: datetime) -> list[Game]`
  - `parse_gamerpower(items: list, now: datetime) -> list[Game]`
  - `clean_gp_title(raw: str) -> str`
  - `fetch_json(url: str) -> object`
  - Sabitler: `EPIC_URL`, `GAMERPOWER_URL`, `STORES`, `TIMEOUT`, `TZ`

- [ ] **Step 1: Testleri yaz**

`freegames.py` dosyasını sadece testlerle oluştur (implementasyon henüz yok):

```python
#!/usr/bin/env python3
"""Epic, Steam ve GOG'daki ücretsiz oyunları Discord kanalına bildirir."""

from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=3))  # TSİ


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

    print("self-test: TAMAM")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Çalıştır: `PYTHONIOENCODING=utf-8 py freegames.py`
Beklenen: `NameError: name 'parse_epic' is not defined`

- [ ] **Step 3: Implementasyonu yaz**

Testlerin **üstüne**, `_self_test()` fonksiyonundan önce ekle:

```python
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

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
```

- [ ] **Step 4: Testin geçtiğini doğrula**

Çalıştır: `PYTHONIOENCODING=utf-8 py freegames.py`
Beklenen: `self-test: TAMAM`

- [ ] **Step 5: Gerçek veriye karşı doğrula**

Geçici bir kontrol çalıştır (dosyaya yazma, sadece terminal):

```bash
PYTHONIOENCODING=utf-8 py -c "import freegames as f, datetime as d; now=d.datetime.now(d.timezone.utc); print([g.title for g in f.parse_epic(f.fetch_json(f.EPIC_URL), now)]); print([(g.store,g.title) for g in f.parse_gamerpower(f.fetch_json(f.GAMERPOWER_URL), now)])"
```

Beklenen: Epic listesinde o hafta bedava olan oyunlar, GamerPower listesinde sadece Epic/Steam/GOG etiketli girdiler. Itch.io veya IndieGala görünürse `STORES` filtresi bozuk demektir.

- [ ] **Step 6: Commit**

```bash
git add freegames.py
git commit -m "feat: Epic ve GamerPower kaynaklarını ayrıştır"
```

---

### Task 2: Tekilleştirme ve durum yönetimi

Aynı oyunun iki kaynaktan gelmesini engelleyen birleştirme ve tekrar bildirimini önleyen `seen.json` mantığı.

**Files:**
- Modify: `freegames.py`

**Interfaces:**
- Consumes: Task 1'den `Game`
- Produces:
  - `dedupe(games: list[Game]) -> list[Game]` — sıralamada önce gelen kazanır
  - `load_seen(path: str) -> dict` — `{key: ends_at_iso}`
  - `prune_seen(seen: dict, now: datetime) -> dict`
  - `save_seen(path: str, seen: dict) -> None`
  - `SEEN_FILE`, `DEFAULT_KEEP_DAYS`

- [ ] **Step 1: Testleri yaz**

`_self_test()` içinde, `print("self-test: TAMAM")` satırının **üstüne** ekle:

```python
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
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Çalıştır: `PYTHONIOENCODING=utf-8 py freegames.py`
Beklenen: `NameError: name 'dedupe' is not defined`

- [ ] **Step 3: Implementasyonu yaz**

`parse_gamerpower`'ın altına ekle:

```python
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
```

- [ ] **Step 4: Testin geçtiğini doğrula**

Çalıştır: `PYTHONIOENCODING=utf-8 py freegames.py`
Beklenen: `self-test: TAMAM`

- [ ] **Step 5: Commit**

```bash
git add freegames.py
git commit -m "feat: tekilleştirme ve seen.json durum yönetimi"
```

---

### Task 3: Discord mesajları

Embed üretimi ve webhook'a gönderim.

**Files:**
- Modify: `freegames.py`

**Interfaces:**
- Consumes: Task 1'den `Game`
- Produces:
  - `game_embed(game: Game) -> dict`
  - `new_games_payloads(games: list[Game]) -> list[dict]` — 10 embed sınırına göre bölünmüş webhook gövdeleri
  - `weekly_payload(games: list[Game]) -> dict`
  - `post_discord(webhook: str, payload: dict) -> None`

- [ ] **Step 1: Testleri yaz**

`_self_test()` içinde, `print("self-test: TAMAM")` satırının **üstüne** ekle:

```python
    # --- game_embed ---
    game = Game("epic:beacon-pines", "Beacon Pines", "Epic",
                "https://store.epicgames.com/tr/p/beacon-pines", "₺149,00",
                "2026-08-20T15:00:00+00:00")
    emb = game_embed(game)
    assert emb["title"] == "Beacon Pines"
    assert emb["url"] == game.url
    assert "Epic" in emb["description"]
    names = [f["name"] for f in emb["fields"]]
    assert names == ["Normal fiyatı", "Son tarih"], names
    # Discord zaman etiketi: <t:UNIX:R> biçiminde olmalı ki herkes kendi saatinde görsün
    assert emb["fields"][1]["value"] == "<t:1787238000:R>", emb["fields"][1]["value"]

    # Fiyat ve tarih bilinmiyorsa o alanlar hiç eklenmemeli
    bare = Game("gp:1", "Dwarven Realms", "Steam", "https://x", "", "")
    assert game_embed(bare)["fields"] == []

    # --- new_games_payloads: Discord bir mesajda en fazla 10 embed alır ---
    many = [Game(f"k{i}", f"Oyun {i}", "Epic", "https://x", "", "") for i in range(23)]
    payloads = new_games_payloads(many)
    assert [len(p["embeds"]) for p in payloads] == [10, 10, 3]
    assert "content" in payloads[0] and payloads[0]["content"]
    assert "content" not in payloads[1]  # başlık sadece ilk mesajda

    # --- weekly_payload: mağazaya göre gruplanmış tek mesaj ---
    weekly = weekly_payload([game, bare])
    text = weekly["content"]
    assert "Epic" in text and "Steam" in text
    assert "Beacon Pines" in text and "Dwarven Realms" in text
    assert weekly["content"].index("Epic") < weekly["content"].index("Steam")

    # Hiç oyun yoksa da anlamlı bir mesaj çıkmalı
    assert weekly_payload([])["content"]
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Çalıştır: `PYTHONIOENCODING=utf-8 py freegames.py`
Beklenen: `NameError: name 'game_embed' is not defined`

- [ ] **Step 3: Implementasyonu yaz**

`save_seen`'in altına ekle:

```python
import time

EMBED_LIMIT = 10          # Discord'un bir mesajdaki embed sınırı
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
    return {
        "title": game.title,
        "url": game.url,
        "description": f"**{game.store}**",
        "color": COLOR_FREE,
        "fields": fields,
    }


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


def weekly_payload(games):
    """Haftalık özet: mağazaya göre gruplanmış tek mesaj."""
    if not games:
        return {"content": "📅 **Haftalık özet** — şu anda ücretsiz oyun yok."}

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
    return {"content": "\n".join(lines)}


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
```

Not: `1787238000`, `2026-08-20T15:00:00+00:00`'ın unix karşılığıdır. Test başarısız olursa beklenen değeri şununla doğrula:
`py -c "import datetime;print(int(datetime.datetime.fromisoformat('2026-08-20T15:00:00+00:00').timestamp()))"`

- [ ] **Step 4: Testin geçtiğini doğrula**

Çalıştır: `PYTHONIOENCODING=utf-8 py freegames.py`
Beklenen: `self-test: TAMAM`

- [ ] **Step 5: Commit**

```bash
git add freegames.py
git commit -m "feat: Discord embed ve webhook gönderimi"
```

---

### Task 4: Ana akış ve komut satırı

Parçaları birleştiren `main()`, hata yönetimi ve CLI bayrakları.

**Files:**
- Modify: `freegames.py`

**Interfaces:**
- Consumes: Task 1-3'ün tamamı
- Produces: `collect(now) -> list[Game]`, `is_weekly_time(now) -> bool`, `main(argv=None) -> int`

- [ ] **Step 1: Testleri yaz**

`_self_test()` içinde, `print("self-test: TAMAM")` satırının **üstüne** ekle:

```python
    # --- is_weekly_time: Pazartesi 09:00 TSİ (= 06:00 UTC) ---
    # Cron saat başı çalışır, bu yüzden pencere tam bir saat genişliğinde.
    assert is_weekly_time(datetime(2026, 8, 17, 6, 5, tzinfo=timezone.utc))    # Pzt 09:05 TSİ
    assert not is_weekly_time(datetime(2026, 8, 17, 7, 5, tzinfo=timezone.utc))  # Pzt 10:05
    assert not is_weekly_time(datetime(2026, 8, 18, 6, 5, tzinfo=timezone.utc))  # Salı
```

- [ ] **Step 2: Testin başarısız olduğunu doğrula**

Çalıştır: `PYTHONIOENCODING=utf-8 py freegames.py`
Beklenen: `NameError: name 'is_weekly_time' is not defined`

- [ ] **Step 3: Implementasyonu yaz**

`post_discord`'un altına, `_self_test`'in üstüne ekle:

```python
import argparse
import os
import sys

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
        payloads.append(weekly_payload(games))

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
```

Dosyanın en altındaki giriş noktasını değiştir:

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Testin geçtiğini doğrula**

Çalıştır: `PYTHONIOENCODING=utf-8 py freegames.py --self-test`
Beklenen: `self-test: TAMAM`

- [ ] **Step 5: Gerçek veriyle uçtan uca dene (Discord'a gönderim yok)**

```bash
PYTHONIOENCODING=utf-8 py freegames.py --dry-run
PYTHONIOENCODING=utf-8 py freegames.py --dry-run --force-weekly
```

Beklenen: JSON gövdeleri ekrana basılır, `seen.json` **oluşmaz** (`git status` temiz kalmalı). Haftalık çıktıda oyunlar mağazaya göre gruplanmış görünmeli.

- [ ] **Step 6: Commit**

```bash
git add freegames.py
git commit -m "feat: ana akış ve komut satırı arayüzü"
```

---

### Task 5: GitHub Actions ve README

Zamanlama, durum dosyasının geri commit'lenmesi ve depo dokümantasyonu.

**Files:**
- Create: `.github/workflows/check.yml`
- Create: `README.md`

**Interfaces:**
- Consumes: `freegames.py`, `DISCORD_WEBHOOK_URL` secret'ı

- [ ] **Step 1: Workflow'u yaz**

`.github/workflows/check.yml`:

```yaml
name: Ücretsiz oyun kontrolü

on:
  schedule:
    # Her saatin 5. dakikasında (UTC). Pazartesi 06:05 UTC = 09:05 TSİ,
    # haftalık özetin çıktığı saat.
    - cron: "5 * * * *"
  workflow_dispatch:

permissions:
  contents: write   # seen.json'u geri commit edebilmek için

concurrency:
  group: freegames  # üst üste binen çalışmalar seen.json'da çakışmasın
  cancel-in-progress: false

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Ücretsiz oyunları kontrol et
        env:
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
        run: python3 freegames.py

      - name: Durum dosyasını kaydet
        run: |
          if [ -n "$(git status --porcelain seen.json)" ]; then
            git config user.name "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git add seen.json
            git commit -m "chore: seen.json güncellendi"
            git push
          fi
```

`ubuntu-latest` imajında Python 3 hazır geldiği için `setup-python` adımı eklenmiyor.

- [ ] **Step 2: Workflow'u elle tetikleyip doğrula**

```bash
git add .github/workflows/check.yml
git commit -m "ci: saatlik kontrol workflow'u"
git push
gh workflow run "Ücretsiz oyun kontrolü"
```

Yaklaşık bir dakika bekleyip:

```bash
gh run list --limit 1
gh run view --log-failed
```

Beklenen: çalışma başarılı. Discord kanalına o an bedava oyun varsa mesaj düşmüş olmalı. `gh run view --log` çıktısında webhook URL'i **görünmemeli**.

- [ ] **Step 3: İkinci çalıştırmanın sessiz kaldığını doğrula**

```bash
gh workflow run "Ücretsiz oyun kontrolü"
```

Beklenen: bu kez Discord'a mesaj gitmez, log'da `Yeni bir şey yok.` yazar. Tekrar bildirim koruması böyle doğrulanır.

- [ ] **Step 4: README'yi yaz**

`README.md`:

````markdown
# Discord Ücretsiz Oyun Botu

Epic Games Store, Steam ve GOG'da ücretsiz dağıtılan oyunları saatlik olarak
takip eder, yenisini bulduğunda Discord kanalına bildirim düşer. Pazartesi
sabahları o an bedava olan her şeyin özetini gönderir.

Sunucu gerekmez, üçüncü parti bağımlılık yoktur — tek bir Python dosyası
GitHub Actions üzerinde çalışır.

## Nasıl çalışır

| Kaynak | Kapsam |
|---|---|
| [Epic Games promosyon endpoint'i](https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions) | Epic'in haftalık ücretsiz oyunları |
| [GamerPower API](https://www.gamerpower.com/api) | Steam, GOG ve Epic'teki diğer kampanyalar |

Bildirilen oyunlar `seen.json`'a yazılır, böylece aynı oyun iki kez
duyurulmaz. Kampanyası biten kayıtlar dosyadan temizlenir; bir oyun aylar
sonra tekrar bedava olursa yeniden bildirilir.

## Kurulum

1. Discord'da hedef kanalda webhook oluştur:
   *Kanal Ayarları → Entegrasyonlar → Webhook'lar → Yeni Webhook*, URL'i kopyala
2. Bu depoyu fork'la, sonra webhook'u secret olarak ekle:

   ```bash
   gh secret set DISCORD_WEBHOOK_URL
   ```

   (veya *Settings → Secrets and variables → Actions → New repository secret*)
3. *Actions* sekmesinden workflow'u etkinleştir. Saat başı kendi çalışır;
   elle denemek için *Run workflow*.

## Lokal kullanım

```bash
python3 freegames.py --dry-run                  # Discord'a göndermeden çıktıyı gör
python3 freegames.py --dry-run --force-weekly   # haftalık özeti dene
python3 freegames.py --self-test                # ağ gerektirmeyen testler
```

Windows'ta `python3` yerine `py`, ayrıca konsol Türkçe karakterde patlarsa
`PYTHONIOENCODING=utf-8` ekle.

Gerçekten göndermek için `DISCORD_WEBHOOK_URL` ortam değişkenini tanımla.
Bu değer depoya **asla** commit edilmemeli — `.env` dosyası `.gitignore`'da.

## Ayarlar

Takip edilen mağazalar `freegames.py` içindeki `STORES` sözlüğünde. Yeni bir
mağaza eklemek için GamerPower'ın `platforms` alanında geçen ismi bir satır
olarak eklemek yeterli.

Haftalık özetin günü ve saati `WEEKLY_WEEKDAY` / `WEEKLY_HOUR` sabitlerinde
(TSİ).
````

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: README"
git push
```

---

### Task 6: Public'e geçiş kontrolü

Depo portfolyoda gösterileceği için, public yapmadan önce sırların geçmişe
sızmadığını doğrula.

**Files:** yok (yalnızca doğrulama)

- [ ] **Step 1: Git geçmişini tara**

```bash
git log -p --all | grep -iE "discord(app)?\.com/api/webhooks/[0-9]{5,}/[A-Za-z0-9_-]{10,}"
```

Desen id ve token kısmını da arar; yalnızca `discord.com/api/webhooks` aramak
bu dokümanların kendi metnini yakalayıp yanlış alarm verir.

Beklenen: **hiçbir çıktı olmamalı.** Çıktı varsa depo public yapılmamalı; önce
Discord'da webhook silinip yenisi oluşturulmalı ve secret güncellenmeli.

- [ ] **Step 2: Takip edilmeyen dosyaları doğrula**

```bash
git ls-files | grep -E "^\.env$"
```

Beklenen: hiçbir çıktı olmamalı.

- [ ] **Step 3: Actions loglarını kontrol et**

```bash
gh run view --log | grep -i "webhooks"
```

Beklenen: hiçbir çıktı olmamalı.

- [ ] **Step 4: Depoyu public yap**

Bu adım yalnızca yukarıdaki üç kontrol de temiz çıktıysa ve kullanıcı onay
verdiyse yapılır:

```bash
gh repo edit Higen5/discord-free-games --visibility public --accept-visibility-change-consequences
```

---

## Notlar

**Bilinen sınırlar (bilinçli):**

- GamerPower'daki Epic girdileriyle Epic'in kendi verisi başlık normalize
  edilerek eşleştirilir. Aynı oyunun iki kaynakta belirgin biçimde farklı
  yazılmış olması hâlinde (alt başlık, "Definitive Edition" farkı) iki kez
  bildirilebilir. Pratikte nadir; olursa `dedupe` içinde eşleştirme
  gevşetilir.
- `seen.json` her çalışmada commit edildiği için depo geçmişinde çok sayıda
  `chore:` commit'i birikir. Rahatsız ederse durum dosyası Actions cache'ine
  taşınabilir, ama cache 7 gün sonra silindiği için tekrar bildirim riski doğar.
- Bitiş tarihi bilinmeyen kampanyalar `seen.json`'da 90 gün tutulur
  (`DEFAULT_KEEP_DAYS`).
