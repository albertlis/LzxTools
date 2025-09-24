<div align="center">
# 🔥 LzxTools - Inteligentny Agregator Ofert

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Aktywny-success.svg)]()

> **Zaawansowany system scrapowania i agregacji ofert z wiodących platform polskich**
</div>

## 🎯 Czym jest LzxTools?

**LzxTools** to potężne narzędzie do automatycznego zbierania, analizowania i prezentowania ofert z trzech największych polskich platform:

- 🏠 **LZX** - Agregator offers z serwisów jak Allegro, OLX itp.
- 🚗 **Otomoto** - Pojazdy i motoryzacja  
- 💎 **Pepper** - Promocje i okazje zakupowe

System został zaprojektowany z myślą o użytkownikach, którzy cenią sobie czas i chcą mieć wszystkie najciekawsze oferty w jednym miejscu, dostarczone prosto do skrzynki mailowej.

> *Używałem go do szukania mieszkania, agregując różne oferty w LZX, jednak tam są limity i darmowy dostęp jest tylko na miesiąc. Otomoto jest wspierane w LZX, więc jest poniekąd redundantne, ale z uwagi na prostotę strony pozwala szybko szukać samochodu bez LZX. Deduplikacja pomaga, gdy deweloper spamuje 100 identycznymi ofertami na Otodom – nie musisz wtedy wszystkiego przeglądać. Analogicznie, jeśli oferta pojawi się na kilku serwisach, zobaczysz ją tylko raz. Pepper dodałem dodatkowo, bo lubię mieć wszystko w jednym newsletterze wysyłanym raz dziennie i nie musieć sam sprawdzać wszystkich źródeł.*


## ✨ Kluczowe Funkcjonalności

### 🤖 Inteligentne Scrapowanie
- **Zaawansowane parsowanie RSS** dla LZX z rozpoznawaniem duplikatów przez analizę obrazów
- **Dynamiczne renderowanie** stron Pepper z obsługą JavaScript (Playwright) z inteligentnym cache'owaniem
- **Wydajne parsowanie HTML** dla Otomoto z inteligentnym cache'owaniem

### 🧠 Inteligentna Dedukcja
- **Wykrywanie duplikatów** na podstawie podobieństwa obrazów (perceptual hashing)
- **Cache'owanie z kompresją** (Zstandard) dla optymalnej wydajności
- **Normalizacja tytułów** i cen dla lepszego grupowania ofert

### 📧 Automatyczne Powiadomienia
- **Eleganckie szablony HTML** z responsywnym designem
- **Automatyczne wysyłanie emaili** z najnowszymi ofertami
- **Harmonogramowanie** - codzienne raporty o wybranej godzinie

### ⚡ Wysoka Wydajność
- **Współbieżne przetwarzanie** linków i obrazów
- **Optymalizowane zapytania** sieciowe z pool'owaniem połączeń  
- **Blokowanie niepotrzebnych zasobów** (obrazy, fonty) podczas scrapowania

## 🚀 Szybki Start

### Wymagania
- Python 3.11+
- Dostęp do internetu
- Konto email z obsługą SMTP

### Instalacja

```bash
# Klonowanie repozytorium
git clone https://github.com/your-username/LzxTools.git
cd LzxTools

# Instalacja zależności (zalecane: uv)
uv sync

# Lub tradycyjnie z pip
pip install -r requirements.txt

# Instalacja przeglądarek dla Playwright
playwright install chromium
```

### Konfiguracja

Utwórz plik `.env` w głównym katalogu:

```env
# Konfiguracja email
SRC_MAIL=twoj-email@gmail.com
SRC_PWD=haslo-aplikacji-gmail
DST_MAIL=odbiorca@gmail.com

# URL do RSS LZX (opcjonalne)
LZX_RSS_URL=https://example.com/rss-feed

# URL do Pepper (opcjonalne - domyślnie najgorętsze)
PEPPER_URL=https://www.pepper.pl/najgoretsze

# URL do Otomoto (wymagane jeśli używasz Otomoto)
OTOMOTO_URL=https://www.otomoto.pl/osobowe/...
```

### Podstawowe Użycie

```bash
# Jednorazowe uruchomienie dla wszystkich serwisów
python main.py --sources pepper,lzx,otomoto --email

# Tylko Pepper bez wysyłania emaila
python main.py --sources pepper

# Harmonogram codziennych raportów o 8:00
python main.py --sources pepper,lzx --email --schedule 08:00

# Tylko analiza - zapisz do test.html
python main.py --sources lzx
```

## 🎨 Zaawansowane Funkcje

### Personalizacja Szablonu HTML

Szablon `template.html` wykorzystuje Jinja2 i oferuje:
- 📱 **Responsywny design** - idealna prezentacja na wszystkich urządzeniach
- 🎨 **Moderne stylowanie** z gradientami i cieniami
- 🖼️ **Inteligentna obsługa obrazów** z fallbackiem dla brakujących zdjęć
- 📊 **Czytelna prezentacja** cen i szczegółów ofert

### Struktura Oferty

Każda oferta zawiera:
```python
{
    "name": "Tytuł oferty z ceną",
    "link": "https://link-do-oferty.pl", 
    "image": "https://url-do-obrazka.jpg",
    "price": "15 000 zł",
    "description": "Dodatkowy opis"  # opcjonalnie
}
```

### Cache i Wydajność

System wykorzystuje zaawansowany cache:
- **Kompresja Zstandard** - oszczędność miejsca na dysku
- **Inteligentne wykrywanie duplikatów** - unikanie spam'u
- **Automatyczne czyszczenie** starych wpisów

## 🔧 Architektura Systemu

### Klasy Bazowe

- **`ScrapperBase`** - Abstrakcyjna klasa bazowa z cache'owaniem
- **`LzxScrapper`** - Zaawansowany parser RSS z analizą obrazów  
- **`PepperScrapper`** - Scrapper z Playwright dla dynamicznych stron
- **`OtomotoScrapper`** - Wydajny parser HTML z BeautifulSoup

### Przepływ Danych

```
RSS/HTML → Parsowanie → Normalizacja → Dedukcja → Cache → HTML Template → Email
```

## 🎛️ Parametry Konfiguracyjne

### Argumenty Linii Poleceń

| Parametr | Opis | Przykład |
|----------|------|----------|  
| `--sources` | Lista serwisów oddzielona przecinkami | `pepper,lzx,otomoto` |
| `--email` | Wysłać email z wynikami | `--email` |
| `--schedule` | Harmonogram dzienny (24h) | `--schedule 08:30` |
| `--once` | Jednorazowe uruchomienie | `--once` |

### Zmienne Środowiskowe

| Zmienna | Wymagana | Opis |
|---------|----------|------|
| `SRC_MAIL` | ✅ | Email źródłowy (SMTP) |
| `SRC_PWD` | ✅ | Hasło aplikacji |
| `DST_MAIL` | ✅ | Email docelowy |
| `LZX_RSS_URL` | ❌* | URL do RSS LZX |
| `PEPPER_URL` | ❌* | URL do Pepper |
| `OTOMOTO_URL` | ❌* | URL do Otomoto |

*wymagane tylko przy użyciu danego serwisu

## 🛠️ Rozwijanie Projektu

### Dodawanie Nowego Scrapera

1. Stwórz klasę dziedziczącą po `ScrapperBase`
2. Zaimplementuj `new_offers_to_dict()` 
3. Dodaj do `SCRAPER_REGISTRY` w `main.py`

```python
class NowyScrapeer(ScrapperBase):
    @staticmethod
    def new_offers_to_dict(offers) -> list[dict[str, str]]:
        return [{"name": o.title, "link": o.url, ...} for o in offers]
```

### Struktura Projektu

```
LzxTools/
├── main.py              # Punkt wejścia i orchestracja
├── scrapper_base.py     # Klasa abstrakcyjna
├── lzx_parser.py        # Scrapper LZX (RSS + analiza obrazów)
├── pepper_scrapper.py   # Scrapper Pepper (Playwright)
├── otomoto_scrapper.py  # Scrapper Otomoto (BeautifulSoup)
├── template.html        # Szablon email HTML
├── pyproject.toml       # Konfiguracja projektu
└── *.pkl.zstd          # Pliki cache (kompresowane)
```

## 🐛 Rozwiązywanie Problemów

### Typowe Problemy

**Problem**: Playwright nie może uruchomić przeglądarki
```bash
# Rozwiązanie
playwright install chromium
# Lub na Windows
playwright install msedge
```

**Problem**: Błąd SMTP przy wysyłaniu email
- Sprawdź hasło aplikacji Gmail (nie hasło główne!)  
- Upewnij się, że 2FA jest włączone w Gmail
- Użyj hasła aplikacji wygenerowanego w ustawieniach Google

**Problem**: Oferty się powtarzają
- Cache działa poprawnie - to oznacza brak nowych ofert
- Usuń pliki `*_cache.pkl.zstd` aby zresetować cache

## 📈 Monitoring i Logi

System wykorzystuje zaawansowane logowanie:
- **INFO** - Główne operacje i statystyki
- **DEBUG** - Szczegółowe informacje o scrapowaniu  
- **ERROR** - Błędy z pełnym stack trace

Przykład wyjścia:
```
2024-01-15 08:00:01 - INFO - Scraping: pepper
2024-01-15 08:00:15 - INFO - Fetched 23 offers from pepper  
2024-01-15 08:00:16 - INFO - Total unique offers: 23
2024-01-15 08:00:18 - INFO - Email sent.
```

## 🤝 Kontrybucje

Projekty jest otwarty na kontrybucje! 

1. **Fork** repozytorium
2. Stwórz **branch** dla nowej funkcjonalności
3. **Commit** zmiany z opisowymi komunikatami
4. **Push** do swojego fork'a
5. Otwórz **Pull Request**

## 📄 Licencja

Projekt jest dostępny na licencji **MIT** - szczegóły w pliku [LICENSE](LICENSE).

---

<div align="center">

**⭐ Jeśli projekt Ci się podoba, zostaw gwiazdkę! ⭐**

Stworzono z ❤️ dla polskiej społeczności deal hunters

</div>
