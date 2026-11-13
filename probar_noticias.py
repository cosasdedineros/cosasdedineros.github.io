
import requests
import trafilatura
import json
import os
import re
import unicodedata
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ARCHIVO_HISTORIAL = "noticias_publicadas.json"
UMBRAL_SIMILITUD = 0.70

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


def normalizar(texto):
    texto = texto.lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        caracter for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )
    texto = re.sub(r"[^a-z0-9 ]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def son_similares(titulo1, titulo2):
    t1 = normalizar(titulo1)
    t2 = normalizar(titulo2)

    if not t1 or not t2:
        return False

    similitud = SequenceMatcher(None, t1, t2).ratio()

    palabras1 = set(t1.split())
    palabras2 = set(t2.split())

    comunes = palabras1.intersection(palabras2)
    union = palabras1.union(palabras2)

    coincidencia = len(comunes) / len(union) if union else 0

    return (
        similitud >= UMBRAL_SIMILITUD
        or coincidencia >= UMBRAL_SIMILITUD
    )


# Fecha actual en España
hoy = datetime.now(ZoneInfo("Europe/Madrid")).date()
fecha_minima = hoy - timedelta(days=2)

# Cargar historial
if os.path.exists(ARCHIVO_HISTORIAL):
    with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as archivo:
        historial = json.load(archivo)
else:
    historial = {"publicadas": []}

publicadas = historial.get("publicadas", [])

urls_publicadas = {
    noticia["url"].rstrip("/")
    for noticia in publicadas
}

titulares_publicados = [
    noticia["titulo"]
    for noticia in publicadas
    if noticia.get("titulo")
]

# Titulares aceptados durante esta ejecución
titulares_candidatos = []

print(f"Fecha de hoy: {hoy}")
print(f"Se aceptan noticias desde: {fecha_minima}")
print(f"Noticias ya publicadas: {len(urls_publicadas)}")

for fuente, titulo, url in NOTICIAS:

    print("\n" + "=" * 80)
    print(f"FUENTE: {fuente}")
    print(f"NOTICIA: {titulo}")

    if url.rstrip("/") in urls_publicadas:
        print("DESCARTADA: ya se publicó anteriormente.")
        continue

    try:
        respuesta = requests.get(url, headers=headers, timeout=20)
        respuesta.raise_for_status()

        descargado = trafilatura.extract(
            respuesta.text,
            include_comments=False,
            include_tables=True
        )

        metadata = trafilatura.extract_metadata(respuesta.text)

        if not metadata or not metadata.date:
            print("DESCARTADA: no se ha podido detectar la fecha.")
            continue

        titulo_real = metadata.title or titulo

        print(f"TÍTULO DETECTADO: {titulo_real}")
        print(f"FECHA DETECTADA: {metadata.date}")

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

        if not descargado or len(descargado) < 900:
            print("DESCARTADA: contenido insuficiente.")
            continue

        # Comparar con noticias ya publicadas
        repetida = False

        for titular_anterior in titulares_publicados:
            if son_similares(titulo_real, titular_anterior):
                print("DESCARTADA: titular similar a una noticia ya publicada.")
                print(f"Coincidencia: {titular_anterior}")
                repetida = True
                break

        if repetida:
            continue

        # Comparar con otras noticias de esta ejecución
        for titular_anterior in titulares_candidatos:
            if son_similares(titulo_real, titular_anterior):
                print("DESCARTADA: posible duplicado de otra noticia candidata.")
                print(f"Coincidencia: {titular_anterior}")
                repetida = True
                break

        if repetida:
            continue

        titulares_candidatos.append(titulo_real)

        print("ACEPTADA: candidata para la newsletter.")
        print(f"CARACTERES EXTRAÍDOS: {len(descargado)}")
        print("\nCONTENIDO:")
        print(descargado[:2500])

    except Exception as error:
        print(f"ERROR: {error}")
