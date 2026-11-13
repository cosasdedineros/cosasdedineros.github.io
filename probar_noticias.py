
import requests
import trafilatura
import feedparser

FUENTES = {
    "Investing - Economía": "https://www.investing.com/rss/news_14.rss",
    "Investing - Mercados": "https://www.investing.com/rss/news_25.rss",
    "BCE": "https://www.ecb.europa.eu/rss/press.html"
}

headers = {
    "User-Agent": "Mozilla/5.0 (compatible; CosasDeDineros/1.0)"
}

for fuente, rss_url in FUENTES.items():
    print("\n" + "=" * 70)
    print(f"FUENTE: {fuente}")
    print("=" * 70)

    try:
        feed = feedparser.parse(rss_url)

        if not feed.entries:
            print("No se han encontrado noticias.")
            continue

        for noticia in feed.entries[:3]:
            titulo = noticia.get("title", "Sin título")
            enlace = noticia.get("link", "")

            print(f"\nTITULAR: {titulo}")
            print(f"ENLACE: {enlace}")

            try:
                respuesta = requests.get(
                    enlace,
                    headers=headers,
                    timeout=20
                )
                respuesta.raise_for_status()

                texto = trafilatura.extract(
                    respuesta.text,
                    include_comments=False,
                    include_tables=True
                )

                if texto:
                    print("\nTEXTO EXTRAÍDO:")
                    print(texto[:4000])
                else:
                    print("\nNO SE HA PODIDO EXTRAER EL TEXTO.")

            except Exception as error:
                print(f"\nERROR AL DESCARGAR: {error}")
