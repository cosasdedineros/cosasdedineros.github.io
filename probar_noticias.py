
import requests
import trafilatura
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ARCHIVO_HISTORIAL = "noticias_publicadas.json"

NOTICIAS = [
    ("Capital Bolsa", "Nvidia y sus resultados",
     "https://www.bolsamania.com/capitalbolsa/noticias/empresas/nvidia-afronta-la-prueba-de-sus-resultados-tras-el-castigo-en-bolsa--24162930.html"),

    ("Capital Bolsa", "Enagás y Teréga",
     "https://www.bolsamania.com/capitalbolsa/noticias/empresas/enagas-eleva-su-participacion-al-495-en-la-francesa-terega-tras-comprar-a-edf-un-18-por-311-millones--24161806.html"),

    ("Capital Bolsa", "Bonos estadounidenses",
     "https://www.bolsamania.com/capitalbolsa/noticias/renta-fija/el-bono-de-eeuu-a-dos-anos-registra-su-mayor-salto-de-rentabilidad-desde-2022--24162584.html"),

    ("Finanzas.com", "CaixaBank y el dividendo",
     "https://www.finanzas.com/ibex-35/caixabank-hace-fuerte-dividendo-15-800-2028-rentabilidad-75.html"),

    ("Finanzas.com", "BBVA y las recompras",
     "https://www.finanzas.com/noticias/bbva-queda-margen-grandes-recompras.html")
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
}

# Fecha actual en España
hoy = datetime.now(ZoneInfo("Europe/Madrid")).date()
fecha_minima = hoy - timedelta(days=2)

# Cargar historial
if os.path.exists(ARCHIVO_HISTORIAL):
    with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as archivo:
        historial = json.load(archivo)
else:
    historial = {"publicadas": []}

urls_publicadas = {
    noticia["url"].rstrip("/")
    for noticia in historial.get("publicadas", [])
}

print(f"Fecha de hoy: {hoy}")
print(f"Se aceptan noticias desde: {fecha_minima}")
print(f"Noticias ya publicadas: {len(urls_publicadas)}")

for fuente, titulo, url in NOTICIAS:

    print("\n" + "=" * 80)
    print(f"FUENTE: {fuente}")
    print(f"NOTICIA: {titulo}")

    # Comprobar si ya se publicó
    if url.rstrip("/") in urls_publicadas:
        print("DESCARTADA: ya se publicó anteriormente.")
        continue

    try:
        respuesta = requests.get(url, headers=headers, timeout=20)
        print(f"CÓDIGO HTTP: {respuesta.status_code}")
        respuesta.raise_for_status()

        descargado = trafilatura.extract(
            respuesta.text,
            include_comments=False,
            include_tables=True
        )

        metadata = trafilatura.extract_metadata(respuesta.text)

        if metadata:
            print(f"TÍTULO DETECTADO: {metadata.title}")
            print(f"FECHA DETECTADA: {metadata.date}")

        # Comprobar fecha
        if not metadata or not metadata.date:
            print("DESCARTADA: no se ha podido detectar la fecha.")
            continue

        try:
            fecha_noticia = datetime.strptime(
                metadata.date[:10], "%Y-%m-%d"
            ).date()
        except ValueError:
            print("DESCARTADA: formato de fecha no válido.")
            continue

        if fecha_noticia < fecha_minima or fecha_noticia > hoy:
            print("DESCARTADA: fuera del periodo de los últimos tres días.")
            continue

        # Comprobar contenido
        if not descargado:
            print("DESCARTADA: no se ha podido extraer el contenido.")
            continue

        if len(descargado) < 900:
            print("DESCARTADA: contenido demasiado corto.")
            continue

        print("ACEPTADA: candidata para la newsletter.")
        print(f"CARACTERES EXTRAÍDOS: {len(descargado)}")
        print("\nCONTENIDO:")
        print(descargado[:2500])

    except Exception as error:
        print(f"ERROR: {error}")
