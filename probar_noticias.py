
import requests
import trafilatura
import json
import os
import re
import unicodedata
from bs4 import BeautifulSoup
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse

ARCHIVO_HISTORIAL = "noticias_publicadas.json"
UMBRAL_SIMILITUD = 0.70
MAX_NOTICIAS_POR_FUENTE = 30

FUENTES = [
    {
        "nombre": "Capital Bolsa",
        "portada": "https://www.bolsamania.com/capitalbolsa/",
        "dominio": "bolsamania.com",
        "permitidas": ["/capitalbolsa/noticias/"]
    },
    {
        "nombre": "Finanzas.com",
        "portada": "https://www.finanzas.com/",
        "dominio": "finanzas.com",
        "permitidas": [
            "/ibex-35/",
            "/mercados/",
            "/renta-fija/",
            "/fondos/",
            "/economia/",
            "/bolsa/",
            "/empresas/",
            "/divisas/"
        ]
    }
]

PALABRAS_EXCLUIDAS = [
    "analisis-tecnico",
    "analisis-tecnicos",
    "trading",
    "finanzas-personales",
    "podcast",
    "podcasts",
    "formacion",
    "curso",
    "publicidad"
]

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    )
}


def normalizar(texto):
    texto = texto.lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        c for c in texto
        if unicodedata.category(c) != "Mn"
    )
    texto = re.sub(r"[^a-z0-9 ]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def son_similares(titulo1, titulo2):
    t1 = normalizar(titulo1)
    t2 = normalizar(titulo2)

    if not t1 or not t2:
        return False

    similitud = SequenceMatcher(None, t1, t2).ratio()

    palabras1 = set(t1.split())
    palabras2 = set(t2.split())
    union = palabras1 | palabras2
    comunes = palabras1 & palabras2

    coincidencia = len(comunes) / len(union) if union else 0

    return (
        similitud >= UMBRAL_SIMILITUD
        or coincidencia >= UMBRAL_SIMILITUD
    )


def cargar_historial():
    if not os.path.exists(ARCHIVO_HISTORIAL):
        return {"publicadas": []}

    with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as archivo:
        return json.load(archivo)


def enlace_valido(url, fuente):
    partes = urlparse(url)

    if fuente["dominio"] not in partes.netloc:
        return False

    if not partes.path.endswith(".html"):
        return False

    if not any(
        ruta in partes.path
        for ruta in fuente["permitidas"]
    ):
        return False

    if any(
        palabra in partes.path.lower()
        for palabra in PALABRAS_EXCLUIDAS
    ):
        return False

    return True


def descubrir_noticias(fuente):
    print(f"\nBuscando en {fuente['nombre']}...")

    try:
        respuesta = requests.get(
            fuente["portada"],
            headers=headers,
            timeout=25
        )
        respuesta.raise_for_status()

        soup = BeautifulSoup(respuesta.text, "html.parser")

        noticias = []
        urls_vistas = set()

        for enlace in soup.find_all("a", href=True):
            url = urljoin(fuente["portada"], enlace["href"])
            url = url.split("#")[0].rstrip("/")

            if not enlace_valido(url, fuente):
                continue

            if url in urls_vistas:
                continue

            titulo = enlace.get_text(" ", strip=True)

            if len(titulo) < 15:
                continue

            urls_vistas.add(url)

            noticias.append({
                "fuente": fuente["nombre"],
                "titulo_portada": titulo,
                "url": url
            })

            if len(noticias) >= MAX_NOTICIAS_POR_FUENTE:
                break

        print(f"Enlaces de artículos encontrados: {len(noticias)}")
        return noticias

    except Exception as error:
        print(f"ERROR al leer {fuente['nombre']}: {error}")
        return []


# Fechas
hoy = datetime.now(ZoneInfo("Europe/Madrid")).date()
fecha_minima = hoy - timedelta(days=2)

# Historial
historial = cargar_historial()
publicadas = historial.get("publicadas", [])

urls_publicadas = {
    noticia["url"].rstrip("/")
    for noticia in publicadas
    if noticia.get("url")
}

titulares_publicados = [
    noticia["titulo"]
    for noticia in publicadas
    if noticia.get("titulo")
]

print(f"Fecha de hoy: {hoy}")
print(f"Se aceptan noticias desde: {fecha_minima}")
print(f"Noticias publicadas anteriormente: {len(publicadas)}")

# Descubrir artículos
noticias_encontradas = []

for fuente in FUENTES:
    noticias_encontradas.extend(
        descubrir_noticias(fuente)
    )

print(f"\nTotal de enlaces encontrados: {len(noticias_encontradas)}")

# Procesar artículos
titulares_candidatos = []
urls_procesadas = set()
aceptadas = 0

for noticia in noticias_encontradas:

    fuente = noticia["fuente"]
    titulo_portada = noticia["titulo_portada"]
    url = noticia["url"]

    print("\n" + "=" * 80)
    print(f"FUENTE: {fuente}")
    print(f"TITULAR: {titulo_portada}")

    if url in urls_publicadas:
        print("DESCARTADA: ya publicada.")
        continue

    if url in urls_procesadas:
        continue

    urls_procesadas.add(url)

    try:
        respuesta = requests.get(
            url,
            headers=headers,
            timeout=25
        )
        respuesta.raise_for_status()

        texto = trafilatura.extract(
            respuesta.text,
            include_comments=False,
            include_tables=True
        )

        metadata = trafilatura.extract_metadata(respuesta.text)

        if not metadata or not metadata.date:
            print("DESCARTADA: no se detecta la fecha.")
            continue

        titulo_real = metadata.title or titulo_portada

        print(f"TÍTULO: {titulo_real}")
        print(f"FECHA: {metadata.date}")

        try:
            fecha_noticia = datetime.strptime(
                metadata.date[:10],
                "%Y-%m-%d"
            ).date()
        except ValueError:
            print("DESCARTADA: fecha no válida.")
            continue

        if fecha_noticia < fecha_minima or fecha_noticia > hoy:
            print("DESCARTADA: fuera de los últimos tres días.")
            continue

        if not texto or len(texto) < 900:
            print("DESCARTADA: contenido insuficiente.")
            continue

        repetida = False

        for anterior in titulares_publicados + titulares_candidatos:
            if son_similares(titulo_real, anterior):
                print("DESCARTADA: titular similar a otro ya utilizado.")
                print(f"Coincidencia: {anterior}")
                repetida = True
                break

        if repetida:
            continue

        titulares_candidatos.append(titulo_real)
        aceptadas += 1

        print("ACEPTADA")
        print(f"CARACTERES: {len(texto)}")
        print(f"URL: {url}")
        print("\nCONTENIDO:")
        print(texto[:2500])

    except Exception as error:
        print(f"ERROR: {error}")


print("\n" + "=" * 80)
print(f"RESUMEN: {aceptadas} noticias candidatas aceptadas.")
