import os
import re
import json
import html
import hashlib
import requests
import trafilatura
import unicodedata
import time

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
    },

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

# Noticias publicadas durante los últimos 7 días.
historial_reciente = []

for noticia in historial.get("publicadas", []):
    try:
        fecha_publicada = datetime.strptime(
            noticia.get("fecha", ""), "%Y-%m-%d"
        ).date()

        if hoy - timedelta(days=7) <= fecha_publicada <= hoy:
            historial_reciente.append({
                "fecha": noticia.get("fecha"),
                "titular": noticia.get("titular"),
                "resumen": noticia.get("resumen"),
                "fuente": noticia.get("fuente")
            })

    except (ValueError, TypeError):
        continue

historial_texto = json.dumps(
    historial_reciente,
    ensure_ascii=False
)

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
- Distribuye las seis noticias entre el mayor número posible de medios.
- Como criterio general, selecciona un máximo de dos noticias por medio.
- Prioriza incluir noticias de al menos cuatro medios diferentes.
- Solo si no hay suficientes noticias interesantes de otros medios,
  puedes seleccionar una tercera noticia de un mismo medio para completar
  las seis.
- Nunca incluyas una tercera noticia si hay otra noticia de calidad
  comparable procedente de un medio diferente.
- José Luis Cava y Estrategias de Inversión cuentan como un único medio.
- No fuerces la inclusión de noticias de un medio si no aportan suficiente
  interés o calidad.

  CONTROL DE REPETICIONES Y SEGUIMIENTO:

Recibirás un historial de las noticias publicadas durante los últimos
siete días.

- Compara cada noticia candidata con ese historial.
- Detecta acontecimientos repetidos aunque cambien el titular o el medio.
- No repitas una noticia si no aporta información sustancialmente nueva.
- No descartes una empresa por haber aparecido anteriormente.
- Puedes volver a seleccionar Nvidia, Santander o cualquier otra empresa
  si existe un acontecimiento nuevo o información relevante.
- Considera interesantes los seguimientos que aporten nuevas cifras,
  decisiones empresariales, resultados o consecuencias económicas.
- Explica qué ha cambiado respecto a la noticia anterior.
- No repitas explicaciones anteriores salvo que sean necesarias.

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
- Tu objetivo es seleccionar seis noticias.
- Antes de devolver menos de seis, revisa todas las candidatas y busca
  alternativas de otros medios o temas financieros.
- Solo devuelve menos de seis cuando realmente no existan suficientes
  noticias diferentes, relevantes y respaldadas por la información recibida.
- Nunca rellenes con noticias dudosas, repetidas o de escaso interés.

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

for intento in range(1, 6):
    try:
        respuesta = cliente.models.generate_content(
            model=MODELO,
            contents=(
                instrucciones
                + "\n\nHISTORIAL DE NOTICIAS PUBLICADAS EN LOS ÚLTIMOS 7 DÍAS:\n"
                + historial_texto
                + "\n\nNOTICIAS CANDIDATAS:\n"
                + noticias_texto
            ),
            config=types.GenerateContentConfig(
                max_output_tokens=12000
            )
        )

        break

    except Exception as e:
        if intento == 5:
            raise

        espera = intento * 15

        print(
            f"Gemini no está disponible. "
            f"Intento {intento}/5. "
            f"Nuevo intento en {espera} segundos."
        )

        time.sleep(espera)
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

print(f"\nArtículos devueltos por Gemini: {len(articulos)}")

for articulo in articulos:
    original = candidatas_por_id.get(str(articulo.get("id")))

    if original:
        print(
            f"  GEMINI: {original['fuente']} | "
            f"{articulo.get('titular', 'Sin titular')}"
        )
    else:
        print(f"  ID NO RECONOCIDO: {articulo.get('id')}")

articulos_validos = []
ids_utilizados = set()
noticias_por_grupo = {}

# Primera pasada: máximo dos noticias por medio.
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

# Segunda pasada: si faltan noticias, permitir una tercera por medio.
if len(articulos_validos) < 6:
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

        if noticias_por_grupo.get(grupo, 0) >= 3:
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
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<!-- GOOGLE ADSENSE -->
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-2646608092155910"
     crossorigin="anonymous"></script>

<!-- GOOGLE ANALYTICS -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-SCX74R28X0"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-SCX74R28X0');
</script>

<!-- TIPOGRAFÍAS -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<meta name="theme-color" content="#F6F4EE">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">

<title>CosasDeDineros - Noticias {fecha_texto}</title>

<style>
/* ═════════ BASE ═════════ */
:root{{
  --verde:#0B6B55;       /* color de marca (acento) */
  --verde-osc:#0F2A23;   /* hero y bloques oscuros */
  --dorado:#F2B84B;      /* ámbar de acento */
  --crema:#F6F4EE;
  --texto:#14211D;
  --tinta:#14211D;
  --suave:#3F4F49;
  --linea:#DAD6C9;
  --pad:max(32px,calc((100% - 1200px)/2 + 32px));
}}
*{{margin:0;padding:0;box-sizing:border-box;}}
html{{scroll-behavior:smooth;}}
body{{
  font-family:"Inter",system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:17px;line-height:1.6;
  background:var(--crema);color:var(--tinta);
  -webkit-font-smoothing:antialiased;
}}
h1,h2,h3{{font-family:"Space Grotesk",system-ui,sans-serif;}}
:focus-visible{{outline:3px solid var(--dorado);outline-offset:2px;}}

/* ═════════ CABECERA ═════════ */
.cabecera{{
  position:sticky;top:0;z-index:1000;
  background:var(--crema);border-bottom:1px solid var(--linea);
}}
.topbar{{
  display:flex;flex-wrap:wrap;align-items:center;gap:12px 24px;
  padding:14px var(--pad) 0;color:var(--tinta);
}}
.marca{{
  display:flex;align-items:center;gap:12px;
  color:var(--tinta);text-decoration:none;
  font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;
  font-size:22px;letter-spacing:-.01em;
}}
.marca svg{{width:40px;height:40px;flex-shrink:0;}}
.usuario-email{{
  font-size:13px;color:var(--verde);font-weight:500;
  display:none;align-items:center;gap:6px;
}}
.usuario-email::before{{content:"●";color:#2e9e57;font-size:10px;}}
.topbar-acciones{{
  display:flex;align-items:center;justify-content:flex-end;
  flex-wrap:wrap;gap:10px 12px;margin-left:auto;
}}
.usuario-box{{align-items:center;gap:10px;}}
.usuario-nombre{{font-size:14px;font-weight:500;color:var(--tinta);}}
.btn-principal,.btn-contorno{{
  display:inline-flex;align-items:center;gap:8px;
  min-height:44px;padding:0 20px;border-radius:999px;
  font:600 15px/1 "Inter",system-ui,sans-serif;
  cursor:pointer;text-decoration:none;
  transition:background .15s,color .15s;
}}
.btn-principal{{background:var(--verde);color:#fff;border:1.5px solid var(--verde);}}
.btn-principal:hover{{background:#09594A;}}
.btn-contorno{{background:transparent;color:var(--tinta);border:1.5px solid var(--tinta);}}
.btn-contorno:hover{{background:var(--tinta);color:var(--crema);}}
.btn-contorno svg{{width:18px;height:18px;flex-shrink:0;}}

nav{{
  display:flex;gap:0 28px;padding:6px var(--pad) 0;
  overflow-x:auto;white-space:nowrap;
  scrollbar-width:none;-webkit-overflow-scrolling:touch;
}}
nav::-webkit-scrollbar{{display:none;}}
nav a{{
  color:var(--tinta);text-decoration:none;
  font-size:16px;font-weight:500;flex-shrink:0;
  padding:12px 0;border-bottom:3px solid transparent;
  transition:color .15s;
}}
nav a:hover{{color:var(--verde);}}
nav a[aria-current="page"]{{font-weight:600;border-bottom-color:var(--verde);}}

/* ═════════ HERO ═════════ */
.hero{{
  position:relative;overflow:hidden;text-align:left;
  background:var(--verde-osc);color:var(--crema);
  padding:104px var(--pad) 120px;
}}
.hero::after{{
  content:"";position:absolute;left:0;right:0;bottom:0;height:58%;
  pointer-events:none;
  background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1200 300' preserveAspectRatio='none'%3E%3Cpath d='M0 280 C200 270 380 230 560 180 C760 125 980 70 1200 20 L1200 300 L0 300 Z' fill='%2314473A' fill-opacity='.55'/%3E%3Cpath d='M0 280 C200 270 380 230 560 180 C760 125 980 70 1200 20' fill='none' stroke='%23F2B84B' stroke-width='3' stroke-linecap='round' vector-effect='non-scaling-stroke'/%3E%3C/svg%3E") bottom/100% 100% no-repeat;
}}
.hero h1,.hero h2{{position:relative;z-index:1;}}
.hero h1{{
  font-weight:700;font-size:clamp(40px,6.4vw,76px);
  line-height:1.04;letter-spacing:-.035em;max-width:1000px;
}}
.hero h2{{
  font-family:"Inter",system-ui,sans-serif;font-weight:500;
  font-size:clamp(18px,2.4vw,26px);line-height:1.35;
  margin-top:20px;color:var(--dorado);opacity:1;max-width:640px;
}}

/* ═════════ FOOTER ═════════ */
footer{{
  background:#14211D;color:#D5DDD8;
  margin-top:96px;padding:56px var(--pad);
  display:grid;grid-template-columns:1fr auto;gap:8px 32px;
  text-align:left;font-size:15px;
}}
footer p{{margin:0;}}
footer strong{{
  font-family:"Space Grotesk",system-ui,sans-serif;font-weight:700;
  font-size:22px;color:var(--crema);
}}
footer p a{{color:#D5DDD8;text-decoration:underline;}}
footer .legal{{
  grid-column:2;grid-row:1/span 2;align-self:start;
  display:flex;flex-wrap:wrap;gap:4px 28px;
}}
footer .legal a{{color:#D5DDD8;text-decoration:none;padding:8px 0;}}
footer a:hover{{color:#fff;}}

/* ═════════ NOTICIAS ═════════ */
.hero{{padding:72px var(--pad) 104px;}}
.hero h1{{font-size:clamp(36px,5.4vw,60px);}}
.hero p{{position:relative;z-index:1;}}
.hero h1 + p{{
  margin-top:20px;max-width:640px;
  font-size:clamp(18px,2.4vw,26px);font-weight:500;line-height:1.35;color:var(--dorado);
}}
.hero p + p{{margin-top:12px;font-size:15px;color:#D5DDD8;}}
.contenido{{
  max-width:1200px;margin:0 auto;padding:72px 32px 0;
  display:flex;flex-direction:column;gap:24px;
}}
.contenido hr{{display:none;}}
article{{
  display:grid;grid-template-columns:minmax(0,1fr) minmax(0,2fr);
  column-gap:56px;align-items:start;
  background:#fff;border:1px solid var(--linea);border-radius:28px;
  padding:48px 56px;
}}
article > h2{{
  grid-column:1;grid-row:1 / span 8;
  font-size:clamp(24px,2.4vw,30px);font-weight:700;line-height:1.2;
  letter-spacing:-.015em;color:var(--tinta);
}}
article > *:not(h2){{grid-column:2;}}
article p{{margin-bottom:16px;font-size:18px;line-height:1.75;color:var(--suave);}}
article p.fuente{{margin:8px 0 0;}}
.fuente a{{
  display:inline-flex;align-items:center;gap:8px;
  min-height:44px;padding:0 20px;
  border:1.5px solid var(--verde);border-radius:999px;
  color:var(--verde);font-size:15px;font-weight:600;text-decoration:none;
  transition:background .15s,color .15s;
}}
.fuente a::after{{content:"→";}}
.fuente a:hover{{background:var(--verde);color:#fff;}}
article ul{{list-style:none;margin-top:14px;font-size:14px;color:var(--suave);}}
article li::before{{content:"Fuente: ";}}
article li a{{color:var(--suave);}}
article li a:hover{{color:var(--verde);}}

/* ═════════ RESPONSIVE / ACCESIBILIDAD ═════════ */
@media(max-width:900px){{
  footer{{grid-template-columns:1fr;}}
  footer .legal{{grid-column:1;grid-row:auto;margin-top:16px;}}
  article{{grid-template-columns:1fr;padding:36px 28px;}}
  article > h2{{grid-column:1;grid-row:auto;margin-bottom:18px;}}
  article > *:not(h2){{grid-column:1;}}
}}
@media(max-width:700px){{
  :root{{--pad:20px;}}
  .hero{{padding:56px var(--pad) 112px;}}
  .hero::after{{height:40%;}}
  .contenido{{padding:48px 20px 0;}}
  article{{padding:28px 22px;border-radius:24px;}}
  article p{{font-size:17px;}}
  .topbar{{gap:10px 16px;padding-top:12px;}}
  .marca{{font-size:19px;gap:10px;}}
  .marca svg{{width:34px;height:34px;}}
  .topbar-acciones{{gap:8px;}}
  .btn-principal,.btn-contorno{{min-height:40px;padding:0 16px;font-size:14px;}}
}}
@media (prefers-reduced-motion:reduce){{
  *{{transition:none!important;scroll-behavior:auto!important;}}
}}
</style>
</head>

<body>

<!-- CABECERA: TOPBAR + NAV -->
<header class="cabecera">

  <!-- TOPBAR -->
  <div class="topbar">
    <a class="marca" href="index.html" aria-label="Cosas de Dineros, inicio">
      <svg viewBox="0 0 40 40" aria-hidden="true"><rect width="40" height="40" rx="10" style="fill:var(--verde)"/><path d="M9 28 L16 20 L22 24 L31 12" fill="none" stroke="#F6F4EE" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><circle cx="31" cy="12" r="3" fill="#F2B84B"/></svg>
      Cosas de Dineros
    </a>
    <span id="usuarioEmail" class="usuario-email"></span>
    <div class="topbar-acciones">
      <button id="btnLogin" class="btn-principal" type="button">Iniciar sesión</button>
      <div id="usuarioBox" class="usuario-box" style="display:none;">
        <span id="usuarioNombre" class="usuario-nombre"></span>
        <button id="btnLogout" class="btn-contorno" type="button">Salir</button>
      </div>
      <a class="btn-contorno"
         href="https://mail.google.com/mail/?view=cm&to=cosasdedinerosresponde@gmail.com&su=Mensaje%20desde%20la%20web&body=Hola%2C%20te%20escribo%20desde%20Cosas%20de%20Dineros"
         target="_blank" rel="noopener">
        <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M4 7l8 6 8-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        Mensaje directo
      </a>
    </div>
  </div>

  <!-- NAV -->
  <nav aria-label="Principal">
    <a href="index.html">Inicio</a>
    <a href="instagram.html">Posts</a>
    <a href="Substack.html">Artículos</a>
    <a href="Calculadoras.html">Calculadoras</a>
    <a href="comparador-fondos.html">Comparador fondos</a>
    <a href="datos.html">Datos</a>
    <a href="Libros.html">Libros</a>
    <a href="noticias.html" aria-current="page">Noticias</a>
  </nav>

</header>

<!-- CABECERA DE LA EDICIÓN -->
<div class="hero">
  <h1>CosasDeDineros</h1>
  <p>Las noticias financieras explicadas sin complicaciones.</p>
  <p>{fecha_texto} · Lectura aproximada: 5 minutos</p>
</div>

<!-- NOTICIAS -->
<div class="contenido">

{contenido_html}

</div>

<!-- FOOTER -->
<footer>
  <p><strong>Cosas de Dineros</strong></p>

  <p>
    Escrito por Alonso Orellana ·
    <a href="https://instagram.com/cosasdedineros" target="_blank" rel="noopener">
      @cosasdedineros
    </a>
  </p>

  <div class="legal">
    <a href="legal.html">Aviso legal</a>
    <a href="cookies.html">Política de cookies</a>
    <a href="privacidad.html">Política de privacidad</a>
  </div>
</footer>

<!-- FIREBASE: INICIO DE SESIÓN -->
<script type="module">
import {{ initializeApp }} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import {{
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  signOut,
  onAuthStateChanged
}} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";

const firebaseConfig = {{
  apiKey: "AIzaSyCYwFgLTVliJXYcFX3mRQ8-XBu-Bw6M_z4",
  authDomain: "cosasdedineros-7dfd9.firebaseapp.com",
  projectId: "cosasdedineros-7dfd9",
  storageBucket: "cosasdedineros-7dfd9.firebasestorage.app",
  messagingSenderId: "573057231036",
  appId: "1:573057231036:web:66b538098b3805d39608b9",
  measurementId: "G-PJ54E4Y971"
}};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const provider = new GoogleAuthProvider();

const btnLogin = document.getElementById("btnLogin");
const btnLogout = document.getElementById("btnLogout");
const usuarioBox = document.getElementById("usuarioBox");
const usuarioNombre = document.getElementById("usuarioNombre");
const usuarioEmail = document.getElementById("usuarioEmail");

btnLogin.addEventListener("click", async () => {{
  try {{
    await signInWithPopup(auth, provider);
  }} catch (error) {{
    console.error("Error al iniciar sesión:", error);
    alert("No se ha podido iniciar sesión. Inténtalo de nuevo.");
  }}
}});

btnLogout.addEventListener("click", async () => {{
  try {{
    await signOut(auth);
  }} catch (error) {{
    console.error("Error al cerrar sesión:", error);
  }}
}});

onAuthStateChanged(auth, (user) => {{
  if (user) {{
    btnLogin.style.display = "none";
    usuarioBox.style.display = "flex";
    usuarioNombre.textContent = user.displayName || user.email;
    usuarioEmail.textContent = user.email || "";
    usuarioEmail.style.display = "flex";
  }} else {{
    btnLogin.style.display = "block";
    usuarioBox.style.display = "none";
    usuarioEmail.style.display = "none";
    usuarioNombre.textContent = "";
  }}
}});
</script>

</body>
</html>
"""

with open(ARCHIVO_SALIDA, "w", encoding="utf-8") as archivo:
    archivo.write(documento)

with open("resultado_newsletter.json", "w", encoding="utf-8") as archivo:
    json.dump(datos, archivo, ensure_ascii=False, indent=2)

# Actualizar historial de noticias publicadas.
urls_historial = {
    noticia.get("url")
    for noticia in historial.get("publicadas", [])
}

for articulo in articulos_validos:
    url = articulo["url_original"]

    if url in urls_historial:
        continue

    historial["publicadas"].append({
        "fecha": hoy.isoformat(),
        "titular": articulo["titular"],
        "resumen": " ".join(articulo["texto"].split())[:600],
        "fuente": articulo["fuente_original"],
        "url": url
    })

    urls_historial.add(url)

with open(ARCHIVO_HISTORIAL, "w", encoding="utf-8") as archivo:
    json.dump(historial, archivo, ensure_ascii=False, indent=2)

print(f"Historial actualizado: {len(historial['publicadas'])} noticias.")

print("\n====================================")
print("NEWSLETTER GENERADA")
print(f"Artículos: {len(articulos_validos)}")
print(f"Archivo: {ARCHIVO_SALIDA}")
print("====================================")
