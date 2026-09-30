# GDM LLM Çalışması

Gestasyonel diyabetle ilgili 30 Türkçe soruya dört dil modelinin verdiği yanıtları toplayan, kör olarak puanlatan ve dışa aktaran akademik çalışma.

Soruların tek kaynağı `data/GDM_Final_30_Soru_Birlesik.xlsx` dosyasıdır: 20 hasta-türevli soru (Q1–Q20) ve 10 kılavuz vakası (K1–K10). `data/questions.json` bu dosyadan üretilir. Elle yalnızca soruya özel kapsamlılık maddeleri yazılır.

Toplam 30 soru × 4 model × 2 tekrar = 240 yanıt. Dört uzman (iki perinatolog, bir endokrinolog, bir diyetisyen) yanıtları kör kodla puanlar. Diyetisyen yalnızca Mutfak/Beslenme ve Oruç eksenlerini görür.

## Mimari

```mermaid
flowchart LR
    Excel["Excel soru havuzu"] --> Importer["question_importer"]
    Importer --> Json["questions.json"]
    Json --> Db["study.db"]
    Yaml["models.yaml"] --> Db
    Db --> Runner["query_runner"]
    Runner --> Db
    Db --> Ui["Streamlit puanlama"]
    Ui --> Db
    Db --> Export["export"]
```

- `src/domain.py` — eksen, soru tipi, rol ve ölçek tanımları
- `src/question_importer.py` — Excel doğrulaması ve JSON üretimi
- `src/database.py` — tablolar ve repository sınıfları
- `src/llm_clients.py` — OpenAI, Anthropic, Gemini ve yerli model. System prompt yok, temperature gönderilmez, düşünme seviyesi sabit
- `src/query_runner.py` — eksik kombinasyonları sorar, okunabilirliği yazar, kör kod atar
- `src/readability.py` — Ateşman ve Bezirci-Yılmaz
- `app/` — çok sayfalı kör puanlama arayüzü
- `src/export.py` — araştırmacı Excel çıktıları
- `analysis/results_analysis.R` — istatistik

Uzman ekranında model adı, sağlayıcı ve tekrar numarası yoktur. Kimlik yalnızca `R001` gibi kör koddur.

## Kurulum

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` içine API anahtarlarını yazın. Anahtarlar koda gömülmez ve loglanmaz.

`config/models.yaml` içindeki sürüm dizgilerini sorgudan hemen önce sağlayıcının model listesinden doğrulayın. Tüm yanıtları tek oturumda toplamak, sağlayıcının model güncellemesi araya girme riskini azaltır. Dönen gerçek sürüm `model_version_returned` alanına yazılır.

## Model ayarları

| Kod | Sağlayıcı | Model | Düşünme seviyesi |
|-----|-----------|-------|------------------|
| M1 | OpenAI | `gpt-6-astra` | medium |
| M2 | Anthropic | `claude-opus-5-5` | medium |
| M3 | Google | `gemini-3.8-flash` | medium |
| M4 | Yerli | `Trendyol/Trendyol-LLM-8B-T1` @ `1aeda72` (bf16, MLX) | düşünme açık (seviye yok) |

Güncel akıl yürüten modeller `temperature` parametresini reddeder ya da yok sayar. Bu yüzden:

- `temperature` gönderilmez; sağlayıcının varsayılan örneklemesi kullanılır. Veritabanında `temperature` boş (NULL) kalır.
- Yanıtı etkileyen tek ayar olan düşünme seviyesi (`reasoning_effort`) üç modelde `medium` olarak sabitlenir ve kaydedilir.
- System prompt gönderilmez. `models.yaml` içine `temperature` ya da dolu `system_prompt` yazılırsa çalışma başlamaz.
- Her soru iki kez sorulur. Örnekleme sabit olmadığı için iki tekrar, modelin kendi içindeki tutarlılığını (test-tekrar test) ölçer. Makalenin yöntem bölümünde bu gerekçe belirtilmelidir.

### Yerli model (M4) kurulumu

Ağırlıklar açık olduğundan sabit bir Hugging Face commit'inden indirilir ve kurum içinde, veri dışarı çıkmadan çalıştırılır. Komutlar proje kök dizininde, sırayla çalıştırılır:

```bash
pip install mlx-lm "huggingface_hub[cli]"

hf download Trendyol/Trendyol-LLM-8B-T1 \
  --revision 1aeda7229465d71662aacd26e6c6e8f167f683a7 \
  --local-dir models/trendyol-llm-8b-t1-1aeda72-hf

mlx_lm.convert --hf-path models/trendyol-llm-8b-t1-1aeda72-hf \
  --mlx-path models/trendyol-llm-8b-t1-1aeda72-bf16

mlx_lm.server --model models/trendyol-llm-8b-t1-1aeda72-bf16 --port 8080 \
  --temp 0.6 --top-p 0.95 --top-k 20
```

- `--model` değeri `models.yaml` içindeki M4 `model_string` ile aynı olmalıdır.
- `--temp 0.6 --top-p 0.95 --top-k 20` modelin kendi `generation_config.json` değerleridir. Verilmezse `mlx_lm.server` açgözlü çözümleme (0.0) kullanır; bu, diğer modellerdeki "sağlayıcı varsayılanı" ilkesiyle çelişir. İstemci yine `temperature` göndermez.
- Sunucu, sorgu çalıştırılırken ayrı bir terminalde açık kalmalıdır.
- Yanıttaki `<think>` düşünme bloğu kaydedilmeden önce ayıklanır; uzmanlar yalnızca nihai yanıtı görür.

Düşünme belirteçleri çıktı sınırından düştüğü için sınır 16.000 belirteç, zaman aşımı 180 saniyedir. Sınıra takılan yanıtın `finish_reason` alanı kaydedilir, logda uyarı çıkar ve çalışma sonunda kesik yanıt sayısı yazılır. Kesik yanıtlar puanlamadan önce gözden geçirilmelidir.

## Kapsamlılık maddeleri

`questions.json` içindeki `checklist` listesi Excel'den gelmez. Her soru için elle doldurulur:

```json
"checklist": [
  {"id": "Q1-1", "label": "175 g/gün karbonhidrat", "category": "Kritik", "weight": 3}
]
```

`weight` isteğe bağlıdır; yazılmazsa 1 sayılır. Her puan için iki oran saklanır: işaretlenen madde yüzdesi (`checklist_pct`) ve ağırlıklı yüzde (`checklist_weighted_pct`).

`python -m src.query_runner --init` Excel'den metinleri yeniler, aynı soru kimliğine ait checklist'i korur ve veritabanına yükler.

## Çalıştırma sırası

```bash
# 1. Veritabanı, sorular, modeller ve dört uzman
python -m src.query_runner --init

# 2. Küçük deneme: 3 soru, 2 model, 1 tekrar
python -m src.query_runner --run --pilot

# 3. Eksik kombinasyonlar. Yarıda kalırsa aynı komut kaldığı yerden sürer.
python -m src.query_runner --run

# 4. 240 yanıt tamamlanınca kör kod. Seed'i not edin.
python -m src.query_runner --assign-codes --seed 2026

# 5. Arayüz
streamlit run app/scoring_app.py

# 6. Puanlama bitince
python -m src.export
```

Pilot ayrı bir veritabanına (`data/pilot.db`) yazılır; ana çalışmanın `study.db` dosyasını kirletmez. İlk pilot çalıştırmasında sorular, modeller ve uzmanlar bu dosyaya otomatik yüklenir. Pilot yanıtlarını arayüzde denemek için:

```bash
python -m src.query_runner --assign-codes --seed 2026 --pilot
GDM_DB_FILE=data/pilot.db streamlit run app/scoring_app.py
```

`DATABASE_URL` tanımlıyken pilot çalışmaz; böylece deneme yanıtları uzak veritabanına gitmez.

Uzman komutları:

```bash
python -m src.manage_evaluators list
python -m src.manage_evaluators add-sample
python -m src.manage_evaluators reset-password --id E1 --new-password yenisifre
```

Şifre yalnızca eklendiği veya yenilendiği anda bir kez gösterilir.

İlk kurulumdaki uzmanlar: E1 Perinatolog 1, E2 Perinatolog 2, E3 Endokrinolog (tüm eksenler), E4 Diyetisyen (mutfak, oruç).

## Puanlama

1. GQS, 1–5
2. Soruya özel kapsamlılık listesi
3. Kültürel uygunluk (CAS), beş madde, 0–2: beslenme, din, sağlık sistemi, yerel koşullar, aile/sosyal pratikler
4. Güvenlik. Evet ise açıklama zorunlu
5. DISCERN, sekiz madde, 1–5

Radyo düğmelerinde ön seçim yoktur.

## Çıktılar

`exports/` klasörü:

- `responses_full.xlsx` — yanıtlar ve metadata
- `scores_wide.xlsx` — yanıt başına uzman puanları
- `scores_long.xlsx` — R için uzun biçim
- `readability.xlsx`
- `summary_stats.xlsx` — ortalama, SS, medyan, IQR

Bu dosyalar model kimliği içerir ve uzmana gösterilmez.

## Okunabilirlik

Ateşman (1997): `198.825 - 40.175 × (hece/kelime) - 2.610 × (kelime/cümle)`

Bezirci-Yılmaz (2010): `karekök(OKS × (0.84×H3 + 1.5×H4 + 3.5×H5 + 26.25×H6))`

H3–H6, cümle başına 3, 4, 5 ve 6+ heceli kelime sayısıdır. Markdown temizlenir; liste maddeleri ayrı cümle sayılır.

## Web'de yayınlama

Sorgu motoru yerelde çalışır. Uzmanlar Streamlit Community Cloud üzerinden yalnızca puanlar. Ücretsiz planda özel alan adı yoktur; GoDaddy üzerinde CNAME açılmaz. Uzmanlara Streamlit'in verdiği `https://....streamlit.app` adresi verilir. Ana site olduğu gibi kalır.

1. Supabase projesinden PostgreSQL bağlantı adresini alın.
2. Repoyu GitHub'a koyun. `.env`, `data/study.db` ve `exports/` commit edilmez. Depo özel (private) olmalıdır; varsayılan uzman şifreleri kodun içindedir.
3. [share.streamlit.io](https://share.streamlit.io) üzerinde ana dosya `app/scoring_app.py` olsun.
4. Secrets alanına şunu yazın. `sslmode=require` satırın sonunda kalır:

```toml
DATABASE_URL = "postgresql://postgres:SIFRE@db.PROJEID.supabase.co:5432/postgres?sslmode=require"
```

5. Soruları ve yanıtları bu veritabanına yüklemek için yerelde `.env` içine aynı `DATABASE_URL` değerini yazıp `--init`, `--run` ve `--assign-codes` komutlarını çalıştırın. API anahtarları Streamlit Secrets'a konmaz.

## Güvenlik

- API anahtarları yalnızca `.env` veya Streamlit Secrets içindedir.
- Log dosyaları `logs/log-YYYY-MM-DD.txt` yoluna yazılır; anahtar ve şifre loglanmaz.
- Zaman damgaları UTC'dir.
- Her model çağrısı 180 saniye zaman aşımı ile korunur. Geçici hatalarda (429, 5xx, zaman aşımı, bağlantı) en fazla üç deneme yapılır. Kimlik doğrulama ve istek hataları (400, 401, 403, 404) tekrarlanmaz.
