# Uutistenlukija.fi

Tekoälyn kuratoima suomalainen uutiskooste.

## Rakenne

```
uutistenlukija/
├── hugo.toml                 # Hugo-sivuston konfiguraatio
├── content/posts/            # Uutisartikkelit (Hugo markdown)
├── themes/uutistenlukija/    # Räätälöity Hugo-teema
├── pipeline/                 # Python-sisältöputki
│   ├── scanner.py            # RSS-syötteiden skannaus
│   ├── rewriter.py           # Artikkelien uudelleenkirjoitus (Anthropic API)
│   ├── publisher.py          # Hugo-sisällön julkaisu ja sivuston rakennus
│   └── run_pipeline.py       # Putken pääajo-ohjelma
├── public/                   # Rakennettu staattinen sivusto
└── requirements.txt          # Python-riippuvuudet
```

## Käyttö

### Riippuvuudet

```bash
pip install -r requirements.txt
```

### Sisältöputki

```bash
export ANTHROPIC_API_KEY="your-key-here"
export HUGO_BIN="/path/to/hugo"  # oletuksena /workspace/hugo
python3 pipeline/run_pipeline.py
```

Putki: skannaa RSS → uudelleenkirjoittaa tekoälyllä → julkaisee Hugo-sivuston.

### Sivuston rakennus (manuaalinen)

```bash
hugo --minify
```

Tuotos: `public/`-hakemisto.

## Kategoriat

Kotimaa, Ulkomaat, Talous, Teknologia, Urheilu, Kulttuuri, Tiede

## RSS-lähteet

- Yle Uutiset
- Iltalehti
- MTV Uutiset
- Kauppalehti
- Taloussanomat
