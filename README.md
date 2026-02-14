# Karol a Kvído

Malý program, který sleduje vystoupení [Karol a Kvído](https://karolakvido.cz/kalendar-koncertu/) a generuje soubor ve formátu iCalendar.

_Vytvořeno za půl hodiny pomocí GPT-5.3-Codex, kód jsem neviděl._

## Funkce

- Když se pustí `uv run karolakvido`, stáhne si https://karolakvido.cz/kalendar-koncertu/ a vezme data o vystoupeních přímo ze seznamu akcí na této stránce. URL je možné změnit přepínačem `--url`, ale výchozí hodnota je tato.
- Data o vystoupeních exportuje do souboru `karolakvido.ics` v adresáři, odkud je program spuštěn. Název a cestu výstupního souboru lze změnit přepínačem `--output`.
- Volitelným přepínačem `--region` lze specifikovat kraj ČR. V takovém případě se v exportu objeví pouze akce z tohoto kraje.
- V iCalendar exportu je datum akce správně vzhledem k tomu, že na webu je vše v časovém pásmu, které používá ČR.
- V iCalendar exportu je vždy uvedena lokace, kde se akce koná.
- V iCalendar exportu je v popisu akce odkaz na detail akce.
- Požadavky na web posílá schválně pomaleji. Pokud server vrátí HTTP 429, program se automaticky ještě zpomalí a stejnou událost zkouší znovu, takže ji nepřeskočí jen kvůli rate limitu.
- Pomocí GitHub Action se jednou týdně program sám spustí a vygeneruje export se všemi akcemi. Pak se spustí v tomtéž běhu ještě jednou a vygeneruje ještě export jen pro Prahu do souboru `karolakvido-praha.ics`. Soubory se uveřejní na internet pomocí GitHub Pages.

## Program

- Používá `uv` pro správu projektu a instalaci závislostí.
- Používá `ruff` pro jednoznačné formátování kódu.
- Používá `pytest` pro testy.
- Pro každý bod sekce „Funkce“ v tomto README má test, který ověřuje, že to funguje.
