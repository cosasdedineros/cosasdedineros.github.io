import os
import re
import json
import html
import hashlib
import requests
import trafilatura
import unicodedata

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urldefrag
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from google import genai
from google.genai import types


# =====================================================
# CONFIGURACIÓN
# =====================================================

MODELO = "gemini-3.1-flash-lite"

ARCHIVO_HISTORIAL = "noticias_publicadas.json"
ARCHIVO_SALIDA = "borrador_newsletter.html"

MIN_CARACTERES = 900
MIN_PALABRAS = 140
MAX_NOTICIAS_POR_FUENTE = 30

FUENTES = [
    {
        "nombre": "Capital Bolsa",
        "grupo": "Capital Bolsa",
        "portada": "https://www.bolsamania.com/capitalbolsa/",
        "dominio": "bolsamania.com",
        "permitidas": ["/capitalbolsa/noticias/"],
        "requiere_html": True
    },
    {
        "nombre": "Finanzas.com",
        "grupo": "Finanzas.com",
        "portada": "https://www.finanzas.com/",
        "dominio": "finanzas.com",
        "permitidas": [
            "/ibex-35/", "/mercados/", "/renta-fija/",
            "/fondos/", "/economia/", "/bolsa/",
            "/empresas/", "/divisas/"
        ],
        "requiere_html": True
    },
    {
        "nombre": "Estrategias de Inversión",
        "grupo": "Estrategias de Inversión",
        "portada": "https://www.estrategiasdeinversion.com/",
        "dominio": "estrategiasdeinversion.com",
        "permitidas": ["/actualidad/", "/analisis/"],
        "requiere_html": False
    },
    {
        "nombre": "José Luis Cava - Estrategias de Inversión",
        "grupo": "Estrategias de Inversión",
        "portada": "https://www.estrategiasdeinversion.com/especial/jose-luis-cava",
        "dominio": "estrategiasdeinversion.com",
        "permitidas": ["/analisis/"],
        "requiere_html": False
    }

    {
        "nombre": "Cinco Días",
        "grupo": "Cinco Días",
        "portada": "https://cincodias.elpais.com/",
        "dominio": "cincodias.elpais.com",
        "permitidas": ["/mercados/", "/companias/", "/economia/"],
        "requiere_html": True
    },
    {
        "nombre": "Expansión",
        "grupo": "Expansión",
        "portada": "https://www.expansion.com/",
        "dominio": "expansion.com",
        "permitidas": ["/mercados/", "/empresas/", "/economia/"],
        "requiere_html": True
    },
    {
        "nombre": "elEconomista",
        "grupo": "elEconomista",
        "portada": "https://www.eleconomista.es/",
        "dominio": "eleconomista.es",
        "permitidas": ["/mercados-cotizaciones/", "/empresas-finanzas/", "/economia/"],
        "requiere_html": True
    },
    {
        "nombre": "El Confidencial",
        "grupo": "El Confidencial",
        "portada": "https://www.elconfidencial.com/",
        "dominio": "elconfidencial.com",
        "permitidas": ["/mercados/", "/empresas/", "/economia/"],
        "requiere_html": True
    },
    {
        "nombre": "Bolsamanía",
        "grupo": "Capital Bolsa",
        "portada": "https://www.bolsamania.com/",
        "dominio": "bolsamania.com",
        "permitidas": ["/noticias/"],
        "requiere_html": True
    },
    {
        "nombre": "Investing.com",
        "grupo": "Investing.com",
        "portada": "https://www.investing.com/",
        "dominio": "investing.com",
        "permitidas": ["/news/"],
        "requiere_html": True
    },
]


TITULARES_EXCLUIDOS = [
    "las 10 acciones con mas impulso",
    "las mejores acciones para",
    "las acciones que debes comprar",
    "cartera recomendada",
    "valores favoritos",
    "oportunidades de compra",
    "compra esta accion",
    "compre esta accion"
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    )
}


# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

def normalizar(texto):
    texto = (texto or "").lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        c for c in texto
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", texto).strip()


def cargar_historial():
    if not os.path.exists(ARCHIVO_HISTORIAL):
        return {"publicadas": []}

    with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as f:
        return json.load(f)


def enlace_valido(url, fuente):
    partes = urlparse(url)
    dominio = partes.netloc.lower().split(":")[0]

    if not (
        dominio == fuente["dominio"]
        or dominio.endswith("." + fuente["dominio"])
    ):
        return False

    if fuente.get("requiere_html", True) and not partes.path.endswith(".html"):
        return False

    if not any(ruta in partes.path for ruta in fuente["permitidas"]):
        return False

    return True


def descubrir_noticias(fuente):
    print(f"Buscando en {fuente['nombre']}...")

    try:
        respuesta = requests.get(
            fuente["portada"],
            headers=HEADERS,
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

            if any(
                frase in normalizar(titulo)
                for frase in TITULARES_EXCLUIDOS
            ):
                continue

            urls_vistas.add(url)

            noticias.append({
                "fuente": fuente["nombre"],
                "grupo": fuente["grupo"],
                "titulo": titulo,
                "url": url
            })

            if len(noticias) >= MAX_NOTICIAS_POR_FUENTE:
                break

        print(f"  Encontrados: {len(noticias)}")
        return noticias

    except Exception as error:
        print(f"  Error: {error}")
        return []


def extraer_articulo(noticia, fecha_minima, hoy, urls_publicadas):
    url = noticia["url"].rstrip("/")

    if url in urls_publicadas:
        return None

    try:
        respuesta = requests.get(
            url,
            headers=HEADERS,
            timeout=25
        )
        respuesta.raise_for_status()

        texto = trafilatura.extract(
            respuesta.text,
            include_comments=False,
            include_tables=True
        )

        metadata = trafilatura.extract_metadata(respuesta.text)

        if not metadata or not metadata.date or not texto:
            return None

        fecha = datetime.strptime(
            metadata.date[:10], "%Y-%m-%d"
        ).date()

        if fecha < fecha_minima or fecha > hoy:
            return None

        palabras = len(texto.split())

        if len(texto) < MIN_CARACTERES or palabras < MIN_PALABRAS:
            return None

        titulo = metadata.title or noticia["titulo"]

        if any(
            frase in normalizar(titulo)
            for frase in TITULARES_EXCLUIDOS
        ):
            return None

        identificador = hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()[:16]

        return {
            "id": identificador,
            "fuente": noticia["fuente"],
            "grupo": noticia["grupo"],
            "titulo": titulo,
            "url": url,
            "fecha": fecha.isoformat(),
            "contenido": texto[:4500]
        }

    except Exception as error:
        print(f"  Error leyendo artículo {url}: {error}")
        return None


# =====================================================
# RECOPILACIÓN DE NOTICIAS
# =====================================================

hoy = datetime.now(ZoneInfo("Europe/Madrid")).date()
fecha_minima = hoy - timedelta(days=2)

historial = cargar_historial()

urls_publicadas = {
    noticia["url"].rstrip("/")
    for noticia in historial.get("publicadas", [])
    if noticia.get("url")
}

print(f"Fecha: {hoy}")
print("Recopilando noticias...\n")

enlaces = []
urls_enlaces_vistas = set()

for fuente in FUENTES:
    enlaces_fuente = descubrir_noticias(fuente)

    for noticia in enlaces_fuente:
        url = noticia["url"].rstrip("/")
        if url not in urls_enlaces_vistas:
            urls_enlaces_vistas.add(url)
            enlaces.append(noticia)

candidatas = []
urls_candidatas_vistas = set()

for noticia in enlaces:
    articulo = extraer_articulo(
        noticia,
        fecha_minima,
        hoy,
        urls_publicadas
    )

    if articulo and articulo["url"] not in urls_candidatas_vistas:
        candidatas.append(articulo)
        urls_candidatas_vistas.add(articulo["url"])
        print(f"ACEPTADA: {articulo['titulo']}")

print(f"\nTotal de candidatas: {len(candidatas)}")

if len(candidatas) < 4:
    raise RuntimeError(
        "Hay menos de cuatro noticias candidatas. "
        "No se generará la newsletter."
    )


# =====================================================
# GENERACIÓN CON GEMINI
# =====================================================

api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("No se encuentra GEMINI_API_KEY.")

cliente = genai.Client(api_key=api_key)

noticias_texto = json.dumps(
    candidatas,
    ensure_ascii=False
)

instrucciones = """
Eres el editor y redactor de CosasDeDineros.

Tu trabajo consiste en seleccionar y redactar seis noticias financieras
diferentes a partir de los artículos que recibirás.

TEMAS:
Bolsa, tipos de interés, inflación, empresas, bancos, deuda,
renta fija, divisas y mercados financieros.

SELECCIÓN:
- Escoge hasta seis noticias; intenta seleccionar seis si hay material
  suficiente y fiable.
- Deben tratar asuntos diferentes.
- No selecciones varias noticias sobre el mismo acontecimiento.
- Prioriza noticias con consecuencias financieras interesantes.
- Descarta recomendaciones de compra y artículos promocionales.
- No elijas noticias simplemente porque tengan titulares llamativos.
- Busca variedad temática: no concentres las seis noticias en la bolsa
  si existen noticias interesantes sobre tipos, inflación, empresas,
  bancos, deuda o renta fija.
- Los análisis de José Luis Cava pueden seleccionarse si aportan una
  explicación o interpretación económica relevante. Identifica claramente
  cuándo se trata de una opinión o previsión del analista, no de un hecho.
- Distribuye las noticias entre los distintos medios disponibles.
- Selecciona como máximo dos noticias de cada medio.
- Intenta incluir noticias de al menos tres medios diferentes.
- José Luis Cava y Estrategias de Inversión cuentan como un único medio.
- No fuerces la inclusión de un medio si sus noticias no aportan suficiente
  interés o calidad.

VERIFICACIÓN:
- Utiliza únicamente los datos y las fuentes incluidos en las noticias
  candidatas. En esta versión no tienes habilitada una herramienta de
  búsqueda externa, así que no afirmes que has realizado búsquedas en Google.
- Comprueba la coherencia de nombres, fechas, cifras y acontecimientos
  con el material recibido.
- No des por cierto un dato solo porque aparezca en un titular.
- Si una afirmación central no está suficientemente respaldada por el
  material disponible, descarta esa noticia o explica la incertidumbre.
- No inventes información para completar una noticia.
- No inventes nombres de fuentes ni direcciones URL.
- En fuentes_verificacion incluye únicamente fuentes y URL que aparezcan
  en las noticias candidatas. Si no hay una fuente adicional, devuelve
  una lista vacía.
- Si no encuentras seis noticias suficientemente interesantes y fiables,
  devuelve menos de seis. Nunca rellenes con noticias dudosas.

ESTILO DE COSASDEDINEROS:

Escribe como si explicaras la noticia a un amigo inteligente
que no trabaja en finanzas.

- Lenguaje cotidiano y frases naturales.
- Explicaciones sencillas, sin jerga innecesaria.
- Directo, entretenido y con ironía ligera cuando encaje.
- Explica por qué importa financieramente lo que ha ocurrido.
- Utiliza ejemplos cuando ayuden a entenderlo.
- No escribas como un periódico económico ni como un banco.
- No repitas ideas ni añadas conclusiones genéricas.
- No conviertas las noticias en recomendaciones de inversión.

TRADUCCIÓN DE JERGA FINANCIERA:

- No utilices expresiones como «el mercado descuenta»,
  «los inversores descuentan» o «el mercado pone en precio».
  Explica qué creen que ocurrirá los inversores y qué decisiones
  están anticipando.
- No uses palabras como «agresivo», «duro», «restrictivo»,
  «moderado» o «flexible» para describir la política monetaria
  sin explicar qué medida concreta significan.
- En vez de decir que la Fed podría ser «más agresiva», especifica
  si se refiere a subir los tipos más, mantenerlos elevados durante
  más tiempo o reducirlos más despacio. Utiliza únicamente la
  explicación respaldada por la noticia.
- Evita expresiones técnicas como «repunte de las rentabilidades»,
  «prima de riesgo», «tasa de descuento», «apetito por el riesgo»,
  «viento de cola» o «viento en contra» si no son necesarias.
  Cuando aparezcan, explica su significado en lenguaje cotidiano.
- No sustituyas una palabra técnica por otra igualmente técnica.
- El lector debe entender la idea sin tener conocimientos financieros
  previos.
- Si no puedes traducir un concepto con seguridad a partir de la
  información disponible, no inventes. Explica únicamente lo que se sabe.
- Siempre que exista una forma más sencilla de expresar una idea,
  utiliza esa forma.

ENFOQUE FINANCIERO:


ENFOQUE FINANCIERO:

Explica los mecanismos económicos y financieros. No te limites a
contar qué ha ocurrido: explica cómo funciona y por qué importa.

- Cada vez que aparezca un concepto económico o financiero relevante,
  explica qué significa, cómo funciona y por qué produce ese efecto.
- No te limites a mencionar una consecuencia: explica la relación
  causa-efecto.
- Utiliza ejemplos numéricos sencillos cuando ayuden a comprender
  el mecanismo.
- Diferencia entre una pérdida real de negocio y un efecto contable
  provocado por los tipos de cambio.
- Si una empresa obtiene ingresos en otra divisa, explica cómo afecta
  la variación del tipo de cambio al convertir esos ingresos a la
  moneda en la que presenta sus resultados.
- No des por entendido que el lector conoce los conceptos financieros.
  Explícalos sin infantilizar al lector.

CONTEXTO DE CIFRAS Y VALORACIONES:

- Nunca presentes una cifra financiera aislada sin explicar qué significa.
- Cuando se mencione un precio objetivo de una acción, indica, si los datos están disponibles:
  1. Cuál era el precio objetivo anterior.
  2. Cuánto ha subido o bajado la valoración del analista, en porcentaje.
  3. Qué potencial de subida o bajada supone respecto a la cotización en la fecha de la noticia.
  4. Qué recomendación mantiene el analista.
- Explica que un precio objetivo es una estimación del analista, no una predicción segura ni una garantía.
- No califiques una valoración como alta, baja, atractiva o cara sin una referencia.
- Si faltan datos, no inventes; indica qué información no está disponible.
- Aplica el mismo criterio a porcentajes, beneficios, deuda, inflación, tipos de interés y otras cifras relevantes.
- Compara con el periodo anterior, las previsiones o una referencia conocida cuando sea útil y esté disponible.

EXTENSIÓN:
Entre 200 y 300 palabras por noticia.

DEVUELVE EXCLUSIVAMENTE JSON VÁLIDO con esta estructura.
No incluyas explicaciones, comentarios ni bloques Markdown fuera del JSON:

{
  "fecha": "AAAA-MM-DD",
  "articulos": [
    {
      "id": "identificador original",
      "titular": "Titular redactado",
      "texto": "Artículo completo en párrafos separados por saltos de línea",
      "fuentes_verificacion": [
        {
          "nombre": "Nombre de la fuente",
          "url": "URL de la fuente"
        }
      ]
    }
  ]
}

No inventes identificadores. Utiliza los ID de los artículos originales.
"""

print("\nEnviando noticias a Gemini...")

respuesta = cliente.models.generate_content(
    model=MODELO,
    contents=(
        instrucciones
        + "\n\nNOTICIAS CANDIDATAS:\n"
        + noticias_texto
    ),
    config=types.GenerateContentConfig(
        max_output_tokens=12000
    )
)

if not respuesta.text:
    raise RuntimeError("Gemini ha devuelto una respuesta vacía.")

resultado = respuesta.text.strip()

# Limpiar posibles bloques Markdown.
resultado = re.sub(r"^```json\s*", "", resultado, flags=re.IGNORECASE)
resultado = re.sub(r"^```\s*", "", resultado)
resultado = re.sub(r"\s*```$", "", resultado)

try:
    datos = json.loads(resultado)
except json.JSONDecodeError as error:
    print("Respuesta recibida de Gemini:")
    print(resultado)
    raise RuntimeError(
        f"Gemini no ha devuelto JSON válido: {error}"
    )

articulos = datos.get("articulos", [])

if not articulos:
    raise RuntimeError("Gemini no ha devuelto artículos.")

# Comprobar que los identificadores pertenecen a noticias originales.
candidatas_por_id = {
    noticia["id"]: noticia
    for noticia in candidatas
}

articulos_validos = []
ids_utilizados = set()
noticias_por_grupo = {}

for articulo in articulos:
    if len(articulos_validos) >= 6:
        break

    original = candidatas_por_id.get(str(articulo.get("id")))

    if not original:
        continue

    if original["id"] in ids_utilizados:
        continue

    if not articulo.get("titular") or not articulo.get("texto"):
        continue

    grupo = original["grupo"]

    if noticias_por_grupo.get(grupo, 0) >= 2:
        continue

    articulo["url_original"] = original["url"]
    articulo["fuente_original"] = original["fuente"]

    articulos_validos.append(articulo)
    ids_utilizados.add(original["id"])
    noticias_por_grupo[grupo] = noticias_por_grupo.get(grupo, 0) + 1

if not articulos_validos:
    raise RuntimeError("No se han podido validar los artículos generados.")


# =====================================================
# GENERAR HTML
# =====================================================

fecha_texto = hoy.strftime("%d/%m/%Y")

contenido_html = ""

for i, articulo in enumerate(articulos_validos, 1):
    verificaciones = ""

    for fuente in articulo.get("fuentes_verificacion", []):
        url = html.escape(fuente.get("url", ""), quote=True)
        nombre = html.escape(fuente.get("nombre", "Fuente"))

        if url.startswith("https://"):
            verificaciones += (
                f'<li><a href="{url}" target="_blank" '
                f'rel="noopener noreferrer">{nombre}</a></li>'
            )

    parrafos = "".join(
        f"<p>{html.escape(p.strip())}</p>"
        for p in articulo["texto"].split("\n")
        if p.strip()
    )

    titular = html.escape(articulo["titular"])
    url_original = html.escape(
        articulo["url_original"], quote=True
    )
    fuente_original = html.escape(articulo["fuente_original"])

    contenido_html += f"""
    <article>
        <h2>{i}. {titular}</h2>
        {parrafos}
        <p class="fuente">
            <a href="{url_original}" target="_blank"
               rel="noopener noreferrer">
                Leer noticia original en {fuente_original}
            </a>
        </p>
        {f"<ul>{verificaciones}</ul>" if verificaciones else ""}
    </article>
    <hr>
    """


documento = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CosasDeDineros - Noticias {fecha_texto}</title>
<style>
body {{
    font-family: Arial, sans-serif;
    max-width: 760px;
    margin: 40px auto;
    padding: 0 20px;
    color: #26352c;
    background: #f8f5ee;
    line-height: 1.7;
}}
h1 {{
    color: #1a3a2a;
    font-size: 32px;
}}
h2 {{
    color: #1a3a2a;
    font-size: 23px;
    line-height: 1.3;
}}
article {{
    margin: 35px 0;
}}
.fuente {{
    font-size: 14px;
}}
a {{
    color: #876c27;
}}
hr {{
    border: 0;
    border-top: 1px solid #d8d2c4;
    margin: 35px 0;
}}
</style>
</head>
<body>
<header>
    <h1>CosasDeDineros</h1>
    <p>Las noticias financieras explicadas sin complicaciones.</p>
    <p>{fecha_texto} · Lectura aproximada: 5 minutos</p>
</header>
{contenido_html}
<footer>
    <p>Un proyecto de CosasDeDineros.</p>
</footer>
</body>
</html>
"""

with open(ARCHIVO_SALIDA, "w", encoding="utf-8") as archivo:
    archivo.write(documento)

with open("resultado_newsletter.json", "w", encoding="utf-8") as archivo:
    json.dump(datos, archivo, ensure_ascii=False, indent=2)

print("\n====================================")
print("NEWSLETTER GENERADA")
print(f"Artículos: {len(articulos_validos)}")
print(f"Archivo: {ARCHIVO_SALIDA}")
print("====================================")
