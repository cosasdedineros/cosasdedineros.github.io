
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

PAGINAS = {
    "Capital Bolsa - Minuto a minuto": "https://www.capitalbolsa.com/capitalbolsa/noticias/minuto-a-minuto",
    "Capital Bolsa - Gurús de mercado": "https://www.capitalbolsa.com/capitalbolsa/noticias/gurus-de-mercado",
    "Finanzas.com": "https://www.finanzas.com"
}

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
}

for nombre, url in PAGINAS.items():

    print("\n" + "=" * 80)
    print(nombre)
    print("=" * 80)

    try:
        respuesta = requests.get(url, headers=headers, timeout=20)
        respuesta.raise_for_status()

        soup = BeautifulSoup(respuesta.text, "html.parser")

        encontrados = set()

        for enlace in soup.find_all("a", href=True):

            titulo = enlace.get_text(" ", strip=True)
            destino = urljoin(url, enlace["href"])

            if len(titulo) < 20:
                continue

            if destino in encontrados:
                continue

            encontrados.add(destino)

            print(f"\nTITULAR: {titulo}")
            print(f"URL: {destino}")

    except Exception as error:
        print(f"ERROR: {error}")
