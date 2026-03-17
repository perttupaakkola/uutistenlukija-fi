# Uutistenlukija.fi

Suomalainen uutismedia — päivän tärkeimmät uutiset.

## Rakenne

```
├── content/posts/          # Artikkelit (Hugo markdown)
├── layouts/                # Hugo-layoutit
├── themes/uutistenlukija/  # Teema (CSS, JS, layoutit)
├── static/                 # Staattiset tiedostot (kuvat, favicon, jne.)
├── pipeline/               # Sisällöntuotantoputki
│   ├── scanner.py          # RSS-syötteiden skannaus
│   ├── researcher.py       # Taustatutkimus ja faktojen tarkistus
│   ├── writer.py           # Artikkelien kirjoittaminen
│   └── publisher.py        # Julkaisu Hugo-sivustolle
└── hugo.toml               # Hugo-konfiguraatio
```

## Kehitys

```bash
hugo server
```

## Julkaisu

```bash
hugo --minify
```
