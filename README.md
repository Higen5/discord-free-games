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

Bir oyunun "şu anda bedava" sayılması için indirim yüzdesinin sıfır olması
yetmez — promosyon penceresinin içinde olunması da gerekir. Aksi hâlde
gelecek haftanın kampanyaları bugün duyurulur.

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
