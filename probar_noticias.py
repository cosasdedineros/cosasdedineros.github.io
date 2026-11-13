
import requests
import trafilatura
import feedparser

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

FUENTES = {
    "Investing - Economía": "https://www.investing.com/rss/news_14.rss",
    "Investing - Mercados": "https://www.investing.com/rss/news_25.rss",
    "Estrategias de Inversión - José Luis Cava": "https://www.estrategiasdeinversion.com/especial/jose-luis-cava",
    "Estrategias de Inversión - Portada": "https://www.estrategiasdeinversion.com",
    "Benzinga España": "https://es.benzinga.com",
    "Rankia": "https://www.rankia.com",
    "Investing.com": "https://es.investing.com",
    "MarketScreener": "https://www.marketscreener.com",
    "Finanzas.com": "https://www.finanzas.com",
    "Capital Bolsa": "https://www.capitalbolsa.com"
}

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
}


def extraer_articulo(url, titulo=""):
    try:
        respuesta = requests.get(
            url,
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
            print(f"\nTITULAR: {titulo}")
            print(f"ENLACE: {url}")
            print("\nTEXTO EXTRAÍDO:")
            print(texto[:4000])
        else:
            print(f"\nNO SE HA PODIDO EXTRAER EL TEXTO: {url}")

    except Exception as error:
        print(f"\nERROR AL DESCARGAR {url}: {error}")


def procesar_rss(fuente, url):
    feed = feedparser.parse(url)

    if not feed.entries:
        print("No se han encontrado noticias en el RSS.")
        return

    for noticia in feed.entries[:3]:
        titulo = noticia.get("title", "Sin título")
        enlace = noticia.get("link", "")

        if enlace:
            extraer_articulo(enlace, titulo)


def procesar_web(fuente, url):
    try:
        respuesta = requests.get(
            url,
            headers=headers,
            timeout=20
        )
        respuesta.raise_for_status()

        soup = BeautifulSoup(respuesta.text, "html.parser")

        dominio = urlparse(url).netloc
        articulos = []
        urls_vistas = set()

        excluidos = [
            "/tag/", "/category/", "/categoria/",
            "/autor/", "/author/", "/contacto",
            "/login", "/registro", "/privacidad",
            "/cookies", "/newsletter", "/search",
            "/buscar", "/aviso-legal"
        ]

        for enlace in soup.find_all("a", href=True):
            link = urljoin(url, enlace["href"])
            parsed = urlparse(link)

            if parsed.netloc != dominio:
                continue

            if link in urls_vistas:
                continue

            if parsed.path in ("", "/"):
                continue

            if any(x in parsed.path.lower() for x in excluidos):
                continue

            if len(parsed.path.strip("/").split("/")) < 2:
                continue

            titulo = enlace.get_text(" ", strip=True)

            if len(titulo) < 15:
                continue

            urls_vistas.add(link)
            articulos.append((titulo, link))

            if len(articulos) >= 5:
                break

        if not articulos:
            print("No se han encontrado enlaces de artículos.")
            return

        print(f"Artículos encontrados: {len(articulos)}")

        for titulo, enlace in articulos:
            extraer_articulo(enlace, titulo)

    except Exception as error:
        print(f"ERROR AL ANALIZAR LA WEB: {error}")


for fuente, url in FUENTES.items():

    print("\n" + "=" * 70)
    print(f"FUENTE: {fuente}")
    print("=" * 70)

    if ".rss" in url.lower() or ".xml" in url.lower():
        procesar_rss(fuente, url)
    else:
        procesar_web(fuente, url)
