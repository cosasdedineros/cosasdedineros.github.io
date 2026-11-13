
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
from urllib.parse import urljoin, urlparse, urldefrag

ARCHIVO_HISTORIAL = "noticias_publicadas.json"

UMBRAL_SIMILITUD = 0.70
MAX_NOTICIAS_POR_FUENTE = 30
MIN_CARACTERES = 900
MIN_PALABRAS = 140

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
    "publicidad",
    "premium",
    "cartera-modelo"
]

# Contenido que suele indicar publicidad o promoción comercial.
TITULARES_PROMOCIONALES = [
    "compre esta accion",
    "compra esta accion",
    "las mejores acciones para",
    "las acciones con mas impulso",
    "las acciones que debes comprar",
    "las acciones para comprar",
    "oportunidades de compra",
    "nuestros valores favoritos",
    "cartera recomendada"
]

EXPRESIONES_PROMOCIONALES = [
    "hazte premium",
    "suscribete ahora",
    "contrata nuestro servicio",
    "acceso exclusivo para suscriptores",
    "nuestro servicio premium",
    "recibe nuestras recomendaciones",
    "cartera modelo premium",
    "aprovecha nuestra oferta"
]

# Frases que indican que se ha extraído un aviso de cookies
# en lugar del contenido real de la noticia.
FRASES_COOKIES = [
    "utilizamos cookies propias y de terceros",
    "aceptar todas las cookies",
    "rechazar todas las cookies",
    "configurar las cookies",
    "consentimiento de cookies",
    "politica de cookies",
    "gestionar el consentimiento",
    "guardar mis preferencias",
    "este sitio utiliza cookies",
    "cookies estrictamente necesarias"
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

    palabras_vacias = {
        "el", "la", "los", "las", "un", "una", "unos", "unas",
        "de", "del", "en", "por", "para", "con", "sin", "y",
        "o", "que", "se", "su", "sus", "al", "como", "tras",
        "sobre", "entre", "ante", "mas", "menos", "ya"
    }

    palabras1 = {
        p for p in t1.split()
        if p not in palabras_vacias and len(p) > 2
    }

    palabras2 = {
        p for p in t2.split()
        if p not in palabras_vacias and len(p) > 2
    }

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
    dominio = partes.netloc.lower().split(":")[0]

    if not (
        dominio == fuente["dominio"]
        or dominio.endswith("." + fuente["dominio"])
    ):
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


def es_contenido_de_cookies(texto):
    texto_normalizado = normalizar(texto)

    coincidencias = sum(
        1 for frase in FRASES_COOKIES
        if normalizar(frase) in texto_normalizado
    )

    return coincidencias >= 2


def es_promocional(titulo, texto):
    titulo_normalizado = normalizar(titulo)
    texto_normalizado = normalizar(texto)

    # Descartar titulares claramente comerciales.
    if any(
        normalizar(frase) in titulo_normalizado
        for frase in TITULARES_PROMOCIONALES
    ):
        return True

    # Descartar artículos cuyo contenido parece una promoción.
    coincidencias = sum(
        1 for frase in EXPRESIONES_PROMOCIONALES
        if normalizar(frase) in texto_normalizado
    )

    return coincidencias >= 2


def contenido_incompleto(texto):
    texto = texto.strip()

    if not texto:
        return True

    # Si termina con una frase muy larga sin puntuación,
    # puede haberse cortado durante la extracción.
    ultimo_fragmento = re.split(r"[.!?]\s+", texto)[-1].strip()

    if (
        len(ultimo_fragmento) > 120
        and not texto.endswith((".", "!", "?", "…", "»", '"', ")"))
    ):
        return True

    # Evitar textos que terminan claramente en una palabra de enlace.
    palabras_finales = normalizar(ultimo_fragmento).split()

    if palabras_finales:
        finales_sospechosos = {
            "que", "porque", "aunque", "cuando", "mientras",
            "pero", "si", "como", "donde", "cuyo", "cuya",
            "y", "o", "de", "del", "con", "para"
        }

        if palabras_finales[-1] in finales_sospechosos:
            return True

    return False


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
            url = urldefrag(url)[0].rstrip("/")

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


# Fechas: hoy y los dos días anteriores.
hoy = datetime.now(ZoneInfo("Europe/Madrid")).date()
fecha_minima = hoy - timedelta(days=2)

# Historial de noticias realmente publicadas.
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

# Descubrir artículos.
noticias_encontradas = []

for fuente in FUENTES:
    noticias_encontradas.extend(
        descubrir_noticias(fuente)
    )

print(f"\nTotal de enlaces encontrados: {len(noticias_encontradas)}")

# Procesar artículos.
titulares_candidatos = []
urls_procesadas = set()
aceptadas = 0

for noticia in noticias_encontradas:

    fuente = noticia["fuente"]
    titulo_portada = noticia["titulo_portada"]
    url = noticia["url"].rstrip("/")

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

        if not texto:
            print("DESCARTADA: no se ha podido extraer el contenido.")
            continue

        # Filtro de cookies.
        if es_contenido_de_cookies(texto):
            print("DESCARTADA: parece un aviso de cookies.")
            continue

        # Filtro de extensión y calidad.
        palabras = len(texto.split())

        if len(texto) < MIN_CARACTERES or palabras < MIN_PALABRAS:
            print(
                f"DESCARTADA: contenido insuficiente "
                f"({len(texto)} caracteres, {palabras} palabras)."
            )
            continue

        if contenido_incompleto(texto):
            print("DESCARTADA: posible extracción incompleta.")
            continue

        # Filtro de promociones.
        if es_promocional(titulo_real, texto):
            print("DESCARTADA: contenido promocional o comercial.")
            continue

        # Evitar titulares repetidos.
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
        print(f"PALABRAS: {palabras}")
        print(f"URL: {url}")
        print("\nCONTENIDO:")
        print(texto[:2500])

    except Exception as error:
        print(f"ERROR: {error}")


print("\n" + "=" * 80)
print(f"RESUMEN: {aceptadas} noticias candidatas aceptadas.")
