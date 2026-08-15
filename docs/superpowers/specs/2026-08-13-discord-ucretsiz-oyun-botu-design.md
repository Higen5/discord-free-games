# Discord Ücretsiz Oyun Takip Botu — Tasarım

**Tarih:** 2026-08-13
**Durum:** Onay bekliyor

## Amaç

Epic Games Store, Steam ve GOG'da ücretsiz dağıtılan oyunları takip edip Discord'da bir kanala bildirim düşmek. İki tip mesaj:

1. **Anlık** — yeni bir ücretsiz oyun görüldüğünde, en geç 1 saat içinde
2. **Haftalık özet** — Pazartesi sabahı, o an ücretsiz olan her şeyin listesi

## Kapsam dışı (bilinçli olarak)

- **Steam "free weekend" (geçici deneme) etkinlikleri.** Bunlar kalıcı olarak
  sende kalan oyunlardan farklı — birkaç günlüğüne herkes bedava oynayabilir
  ama satın almazsın. GamerPower'ın `type=game` uç noktasında bu tür etkinlikler
  görünmüyor; Steam'in bunun için resmi/belgelenmiş bir API'si de yok (en
  yakın yol `featuredcategories` uç noktasındaki `specials` listesinde
  `discount_percent: 100` olan girdileri yakalamak). 2026-08-16'da bilinçli
  olarak dışarıda bırakıldı: free weekend'ler haftada birkaç kez olduğu için
  dahil etmek bildirim sıklığını belirgin artırır ve "kalıcı bedava oyun"
  takibinin amacından sapar.

- Slash komutları, kullanıcı etkileşimi, bildirim rolleri — kullanıcı "sadece bildirim" dedi
- Gerçek bir Discord bot süreci (gateway bağlantısı, token, izin yönetimi) — tek yönlü mesaj için webhook yeterli
- GOG için ayrı scraper — aşağıya bakınız
- Veritabanı — `seen.json` yeterli

## Veri kaynakları

İkisi de kimlik doğrulama gerektirmiyor, 2026-08-13'te canlı olarak doğrulandı.

### Epic Games (birincil)

```
https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=tr-TR&country=TR&allowCountries=TR
```

Epic'in kendi endpoint'i. Aktif ve yaklaşan promosyonları başlangıç/bitiş tarihleriyle döner. `discountSetting.discountPercentage` alanı "indirimden sonra kalan yüzde" anlamına gelir, yani 0 = bedava.

Bir oyunun **şu anda** ücretsiz sayılması için üç şart birden gerekir (canlı veriyle doğrulandı):

1. Promosyon `promotions.promotionalOffers` altında olmalı — `upcomingPromotionalOffers` değil
2. `discountSetting.discountPercentage == 0`
3. Şu an `startDate <= now < endDate` penceresinin içinde olmalı

Üçüncü şart olmazsa yanlış bildirim çıkar: doğrulama sırasında `Caravan SandWitch` ve `Cardpocalypse` girdileri `discountPercentage == 0` taşıyordu ama promosyonları henüz başlamamıştı (`upcomingPromotionalOffers`, fiyatları hâlâ tam). Sadece yüzdeye bakan bir filtre bunları "şu an bedava" diye duyururdu.

Ayrıca `price.totalPrice.originalPrice > 0` şartı aranır — bu, zaten kalıcı olarak ücretsiz olan (free-to-play) oyunları promosyonlardan ayırır.

**Oyun linki:** `productSlug` alanı çoğu girdide `null` geliyor. Slug sırayla `offerMappings[].pageSlug` → `catalogNs.mappings[].pageSlug` → `urlSlug` içinden ilk dolu olandan alınır. Link: `https://store.epicgames.com/tr/p/<slug>`

### GamerPower (Steam, GOG ve diğerleri)

```
https://www.gamerpower.com/api/giveaways?type=game
```

`platforms` alanı `"PC, Steam"`, `"PC, Epic Games Store"`, `"PC, DRM-Free"` gibi değerler taşır. `type=game` filtresi kalıcı olarak sahip olunan oyunları getirir (DLC ve oyun içi eşya kampanyalarını dışarıda bırakır).

**GOG notu:** GamerPower GOG'u destekliyor, doğrulandı. `?platform=gog` sorgusu `"No active giveaways available at the moment"` döner; tanınmayan bir platform ise `"No category found"` döner. İki yanıtın farklı olması platformun geçerli olduğunu, sadece o an aktif kampanya bulunmadığını gösteriyor (GOG giveaway'leri yılda birkaç kez oluyor).

Bu yüzden GOG için ayrı scraper yazılmıyor — gerekmiyor. Kaynak bir GOG kampanyası listelediğinde kod değişikliği olmadan yakalanacak.

**Mağaza eşleştirmesi** `platforms` alanındaki isimle yapılır (`"Epic Games Store"`, `"Steam"`, `"GOG"`). `"DRM-Free"` etiketine güvenilmez: doğrulama sırasında DRM-Free girdilerinin tamamı IndieGala ve Itch.io çıktı, GOG değil.

**Platform filtresi:** Tek istek atılır ve sonuç istemci tarafında filtrelenir; platform başına ayrı istek atmak üç HTTP çağrısı demek olurdu. Kapsanan mağazalar Epic, Steam, GOG. Itch.io, IndieGala, Ubisoft Connect ve mobil kampanyalar dışarıda bırakılır — sadece bugünkü veride 12 Itch.io/IndieGala girdisi var, bunlar dahil edilse bildirimler çöplüğe dönerdi. Liste koddaki tek bir kümede tutulur, genişletmek tek satır.

### Kaynak çakışması

Epic oyunları her iki kaynakta da görünebilir. Tekilleştirme oyun başlığının normalize edilmiş hali (küçük harf, boşluklar kırpılmış) üzerinden yapılır; Epic'in kendi verisi öncelikli, çünkü tarihleri kesin.

## Mimari

Tek Python dosyası, sıfır üçüncü parti bağımlılık (`urllib.request` + `json` stdlib'de). Kurulum adımı yok, `requirements.txt` yok.

```
freegames.py              # tüm mantık
seen.json                 # bildirilmiş oyunların kimlikleri
.github/workflows/check.yml
```

### Akış

```
saatlik tetikleme
      │
      ├─→ Epic endpoint'i çek ──┐
      │                          ├─→ birleştir + tekilleştir ─→ tam liste
      └─→ GamerPower'ı çek ─────┘                                    │
                                                                      │
                        ┌─────────────────────────────────────────────┤
                        │                                             │
                  Pazartesi 09:00 mu?                    seen.json'da olmayanlar
                        │                                             │
                  haftalık özet mesajı                      anlık bildirim mesajı
                        │                                             │
                        └──────────→ Discord webhook ←────────────────┘
                                                                      │
                                                            seen.json güncelle + commit
```

Pazartesi çalışmasında hem yeni oyun bildirimi hem haftalık özet çıkabilir; ikisi ayrı mesaj olarak gider.

### Tekrar bildirimi önleme

`seen.json` bildirilmiş oyunların kimliklerini tutar. Kimlik = `kaynak:normalize edilmiş başlık` (ör. `epic:beacon pines`). Kampanya bitiş tarihi geçen girdiler dosyadan temizlenir; aynı oyun aylar sonra tekrar bedava olursa yeniden bildirilir.

Zaman penceresine (ör. "son 1 saatte eklenenler") güvenmek daha az kod olurdu ama bir çalışma hata alırsa o bildirim kalıcı olarak kaçar. Dosya bunu engelliyor.

Dosyayı GitHub Actions her çalışmada geri commit eder.

### Mesaj biçimi

Discord webhook'una `POST`, `embeds` alanı kullanılarak:

- **Anlık:** her oyun için bir embed — başlık, mağaza, normal fiyatı, bitiş tarihi, mağaza linki ve sağ üstte küçük kapak görseli (Epic'te `keyImages` içindeki `Thumbnail`, GamerPower'da `thumbnail` alanı; görsel yoksa alan hiç eklenmez)
- **Haftalık:** tek mesaj, mağazaya göre gruplanmış liste

Discord bir mesajda en fazla 10 embed kabul eder; fazlası varsa mesaj bölünür.

## Hata yönetimi

- Bir kaynak hata verir/zaman aşımına uğrarsa: uyarı basılır, diğer kaynakla devam edilir. Tek kaynağın çökmesi tüm çalışmayı düşürmez.
- **Her iki** kaynak da başarısızsa: çıkış kodu 1, `seen.json` değiştirilmez (yoksa oyunlar "bildirilmiş" sayılıp kaybolur).
- Webhook `POST` başarısızsa: çıkış kodu 1 ve `seen.json` **kaydedilmez** — bir sonraki çalışma tekrar dener.
- Discord rate limit (429): `Retry-After` kadar bekle, bir kez tekrar dene.
- Ağ çağrılarında 20 saniye zaman aşımı.

## Yapılandırma

- `DISCORD_WEBHOOK_URL` — ortam değişkeni. GitHub'da repository secret, lokalde `.env` (`.gitignore`'da).
- Başka ayar yok. Sabit kalacak değerler için yapılandırma yazılmayacak.

## Zamanlama

GitHub Actions cron, saat başı. Epic promosyonları Perşembe 18:00 (TSİ) civarı değişir; saatlik kontrol fazlasıyla yeterli, daha sıkı aralık sadece boşa çalışma üretir.

Haftalık özet ayrı bir workflow değil: script çalışma anının Pazartesi 09:00 (TSİ) olup olmadığına bakar. GitHub Actions UTC kullandığı için cron UTC'ye göre yazılır.

Not: GitHub Actions cron'u yoğunlukta birkaç dakika gecikebilir, ayrıca 60 gün boyunca hiç aktivite olmayan depoda zamanlanmış workflow'ları devre dışı bırakır. `seen.json` commit'leri her çalışmada aktivite ürettiği için bu sorun kendiliğinden çözülüyor.

## Test

- `--dry-run`: mesajları Discord'a göndermek yerine terminale basar, `seen.json`'a dokunmaz. Webhook URL'i olmadan çalışır.
- `--force-weekly`: Pazartesi beklemeden haftalık özeti üretir (dry-run ile birlikte kullanılır).
- Dosya içinde `assert` tabanlı bir öz-kontrol: parse mantığını sabit örnek JSON ile doğrular (Epic'in `discountPercentage == 0` filtresi, tekilleştirme, süresi dolmuş kayıtların temizlenmesi). `python freegames.py --self-test` ile çalışır, ağ erişimi gerektirmez. Test framework'ü kurulmayacak.

## Depo ve gizlilik

`Higen5/discord-free-games`. Geliştirme boyunca private; proje bittiğinde portfolyoda gösterilmek üzere public yapılacak.

Actions kotası: private'ken aylık 2000 dakikalık ücretsiz kotadan yiyor (saatlik çalışma ~700-750 dakika, sığıyor). Public'e geçince Actions dakikası sınırsız oluyor.

**Webhook URL'i git geçmişine hiçbir zaman girmemeli.** Repo sonradan public olacağı için bu kritik: geçmişe bir kez giren sır, dosya sonradan silinse bile commit geçmişinde kalır ve URL'i ele geçiren herkes kanala mesaj atabilir. Alınan önlemler:

- `.env` ilk commit'ten itibaren `.gitignore`'da — webhook lokalde sadece bu dosyada durur
- Üretimde değer GitHub repository secret'ında (`DISCORD_WEBHOOK_URL`), kodda veya workflow YAML'ında düz metin olarak geçmez
- Actions loglarına sızmaması için script webhook URL'ini hiçbir hata mesajında basmaz
- Public'e geçmeden önce geçmiş taranır (desen id/token içerir, yoksa bu satırın kendisi eşleşir):
  `git log -p --all | grep -iE "discord(app)?\.com/api/webhooks/[0-9]{5,}/[A-Za-z0-9_-]{10,}"` boş dönmeli

URL sızarsa çözüm basit: Discord'da webhook'u sil, yenisini oluştur, secret'ı güncelle.

## README

Depo portfolyoda görüneceği için kısa bir README yazılacak: ne yaptığı, örnek mesaj görüntüsü, nasıl kurulacağı (webhook oluştur → secret ekle → workflow'u etkinleştir), kullanılan kaynaklar. Uzun dokümantasyon değil, tek sayfa.
