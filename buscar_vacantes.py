#!/usr/bin/env python3
"""Busca vacantes en JSearch (OpenWeb Ninja) y en el Portal del Empleo (STPS) y guarda las de la zona centro o remotas.

Documentación de la API: https://www.openwebninja.com/api/jsearch
Especificación usada:   https://openwebninja.s3.us-east-1.amazonaws.com/portal/openapi/jsearch.yaml
  GET https://api.openwebninja.com/jsearch/search-v2, encabezado x-api-key.
  Cada página (hasta 10 vacantes) consume un crédito, por eso num_pages = 1.

La clave se lee de la variable de entorno JSEARCH_API_KEY (secreto de GitHub). JSearch solo usa la biblioteca
estándar; el Portal del Empleo necesita Playwright (si falta, se registra en «errores» y se sigue).
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

API_URL = "https://api.openwebninja.com/jsearch/search-v2"
CONSULTAS = [
    "analista presupuestal",
    "analista financiero jr",
    "auxiliar contable",
    "analista contable jr",
    "control presupuestal",
    "finanzas públicas",
    "analista de datos financieros",
    "recién egresado finanzas",
    "contabilidad gubernamental",
]
PAIS = "mx"
PUBLICADAS = "3days"
LIMITE_DIA = 9
LIMITE_MES = 190
TZ = ZoneInfo("America/Mexico_City")
RAIZ = Path(__file__).resolve().parent
ARCHIVO_USO = RAIZ / "uso.json"
CARPETA = RAIZ / "resultados"
LARGO_EXTRACTO = 280


def norm(texto):
    """Minúsculas, sin acentos ni signos: 'Méx.' -> 'mex', 'Ciudad de México' -> 'ciudad de mexico'."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


SIN_ESPECIFICAR = "sin especificar"
# Nombres y abreviaturas de cada estado de la zona, ya normalizados (sin acentos, minúsculas, sin puntos).
ESTADOS = {
    "Ciudad de México": {"ciudad de mexico", "cdmx", "cd mx", "mexico city", "mexico city cdmx", "distrito federal",
                         "df", "d f", "cd de mexico", "cd mexico", "mexico df", "mexico d f", "ciudad de mexico cdmx",
                         "ciudad de mexico df", "ciudad de mexico d f"},
    "Estado de México": {"estado de mexico", "state of mexico", "mexico state", "edo de mexico", "edo mexico",
                         "edo de mex", "edo mex", "edomex", "mex", "estado de mex"},
    "Hidalgo": {"hidalgo", "hgo", "estado de hidalgo"},
    "Tlaxcala": {"tlaxcala", "tlax", "estado de tlaxcala"},
    "Puebla": {"puebla", "pue", "estado de puebla"},
}
# Los demás estados, para descartar con seguridad «Monterrey, N.L.» o «Jalisco».
FUERA = {"aguascalientes", "ags", "baja california", "b c", "bc", "baja california sur", "b c s", "bcs",
         "campeche", "camp", "chiapas", "chis", "chihuahua", "chih", "coahuila", "coahuila de zaragoza", "coah",
         "colima", "col", "durango", "dgo", "guanajuato", "gto", "guerrero", "gro", "jalisco", "jal",
         "michoacan", "michoacan de ocampo", "mich", "morelos", "mor", "nayarit", "nay", "nuevo leon", "n l", "nl",
         "oaxaca", "oax", "queretaro", "queretaro de arteaga", "qro", "quintana roo", "q r", "q roo", "qroo",
         "san luis potosi", "s l p", "slp", "sinaloa", "sin", "sonora", "son", "tabasco", "tab", "tamaulipas",
         "tamps", "tamp", "veracruz", "veracruz de ignacio de la llave", "ver", "yucatan", "yuc", "zacatecas", "zac"}
# Lo que solo dice el país: si no hay nada más, la ubicación queda «sin especificar».
SOLO_PAIS = {"mexico", "mx", "republica mexicana", "toda la republica", "toda la republica mexicana", "todo mexico"}
# Ciudades, alcaldías y municipios; se buscan como palabras completas dentro del texto
# («Toluca de Lerdo» contiene «toluca», «Naucalpan de Juárez» contiene «naucalpan»).
CIUDADES = {
    "Ciudad de México": {"ciudad de mexico", "cdmx", "mexico city", "alvaro obregon", "azcapotzalco",
                         "benito juarez", "coyoacan", "cuajimalpa", "cuauhtemoc", "gustavo a madero", "iztacalco",
                         "iztapalapa", "magdalena contreras", "miguel hidalgo", "milpa alta", "tlahuac", "tlalpan",
                         "venustiano carranza", "xochimilco", "santa fe", "polanco"},
    "Estado de México": {"toluca", "naucalpan", "tlalnepantla", "ecatepec", "texcoco", "nezahualcoyotl", "neza",
                         "atizapan", "cuautitlan", "cuautitlan izcalli", "huixquilucan", "interlomas", "metepec",
                         "tultitlan", "coacalco", "chalco", "ixtapaluca", "nicolas romero", "tecamac", "zumpango",
                         "lerma", "chimalhuacan", "zinacantepec", "tultepec", "huehuetoca", "tepotzotlan",
                         "ocoyoacac", "san mateo atenco", "chicoloapan", "ciudad satelite", "acolman"},
    "Hidalgo": {"pachuca", "mineral de la reforma", "tizayuca", "apan", "tulancingo", "tula de allende",
                "huejutla", "actopan", "ixmiquilpan", "tepeji del rio", "ciudad sahagun", "tepeapulco", "zempoala"},
    "Tlaxcala": {"tlaxcala", "calpulalpan", "apizaco", "huamantla", "chiautempan", "zacatelco", "tlaxco"},
    "Puebla": {"puebla", "cholula", "atlixco", "tehuacan", "san martin texmelucan", "huauchinango", "teziutlan",
               "cuautlancingo", "amozoc"},
}
# De la más larga a la más corta, para que «cuautitlan izcalli» gane a «cuautitlan».
_CIUDADES_ORDEN = sorted(((alias, nombre) for nombre, c in CIUDADES.items() for alias in c), key=lambda x: -len(x[0]))
PALABRAS_REMOTO = ("remoto", "remota", "remote", "home office", "desde casa", "teletrabajo",
                   "anywhere", "cualquier lugar", "trabajo a distancia")
PERIODOS = {"HOUR": "por hora", "DAY": "al día", "WEEK": "a la semana", "MONTH": "al mes", "YEAR": "al año"}


def ahora():
    return datetime.now(TZ)


# ---------- Contador de consultas ----------
def leer_uso(hoy):
    try:
        uso = json.loads(ARCHIVO_USO.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        uso = {}
    mes, dia = hoy.strftime("%Y-%m"), hoy.strftime("%Y-%m-%d")
    if uso.get("mes") != mes:
        uso["mes"], uso["consultas_mes"] = mes, 0
    if uso.get("dia") != dia:
        uso["dia"], uso["consultas_dia"] = dia, 0
    uso["limite_dia"], uso["limite_mes"] = LIMITE_DIA, LIMITE_MES
    uso.setdefault("historial", {})
    return uso


def guardar_uso(uso):
    ARCHIVO_USO.write_text(json.dumps(uso, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ignorar_limite_dia():
    """Corrida manual con la casilla «ignorar_limite_dia»: solo se respeta el límite del mes."""
    return os.environ.get("IGNORAR_LIMITE_DIA", "").strip().lower() == "true"


def quedan(uso):
    mes = LIMITE_MES - uso["consultas_mes"]
    if ignorar_limite_dia():
        return max(0, min(len(CONSULTAS), mes))
    return max(0, min(LIMITE_DIA - uso["consultas_dia"], mes))


# ---------- API ----------
class ErrorClave(Exception):
    pass


def buscar(consulta, clave):
    params = {"query": consulta, "country": PAIS, "date_posted": PUBLICADAS, "num_pages": 1}
    req = urllib.request.Request(API_URL + "?" + urllib.parse.urlencode(params),
                                 headers={"x-api-key": clave, "Accept": "application/json",
                                          "User-Agent": "vacantes-diarias/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            datos = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", "replace")[:300]
        if e.code in (401, 403):
            raise ErrorClave(f"HTTP {e.code}: la clave no es válida o no tiene acceso a JSearch. {cuerpo}")
        if e.code == 429:
            raise ErrorClave(f"HTTP 429: se agotó el límite de la API. {cuerpo}")
        raise RuntimeError(f"HTTP {e.code}: {cuerpo}")
    data = datos.get("data") or {}
    trabajos = data.get("jobs") if isinstance(data, dict) else data
    return trabajos or []


# ---------- Filtros y formato ----------
def lugar_completo(job):
    """Ubicación tal como la escribe la API, sin el portal: 'México (y 1 ubicación más) • a través de X' -> 'México (y 1 ubicación más)'."""
    t = str(job.get("job_location") or "").split("•")[0]
    return " ".join(t.split()).strip(" ,")


def lugar(job):
    """Ubicación para filtrar, sin '(y N ubicaciones más)': 'Pachuca de Soto, Hgo.' ."""
    t = re.sub(r"\(y \d+ ubicaci[oó]n(es)? m[aá]s\)", "", lugar_completo(job))
    return " ".join(t.split()).strip(" ,")


def es_remoto(job):
    if job.get("job_is_remote"):
        return True
    texto = norm(" ".join([str(job.get("job_title") or ""), lugar(job), str(job.get("job_city") or "")]))
    return any(norm(p) in texto for p in PALABRAS_REMOTO)


def _contiene(texto, alias):
    return f" {alias} " in f" {texto} "


def zona(job):
    """Devuelve el estado de la zona, SIN_ESPECIFICAR (solo dice «México» o no trae ciudad) o None (fuera de la zona).

    1. Estados: el campo job_state y cada parte de la ubicación, de la última a la primera
       («Toluca de Lerdo, Méx.» -> «mex»). Un estado de fuera descarta aunque la ciudad se llame igual
       que una de la zona («Cuauhtémoc, Chih.», «Benito Juárez, Q.R.»).
    2. Ciudades: el campo job_city y cada parte de la ubicación, buscando la ciudad como palabras completas.
    3. Si no queda nada más que el país, la ubicación está sin especificar; si trae otra ciudad, está fuera.
    """
    estado, ciudad = norm(job.get("job_state")), norm(job.get("job_city"))
    partes = [norm(p) for p in lugar(job).split(",")]
    partes = [p for p in partes if p and p not in SOLO_PAIS]
    for texto in [estado] + partes[::-1]:
        if not texto or texto in SOLO_PAIS:
            continue
        for nombre, alias in ESTADOS.items():
            if texto in alias:
                return nombre
        if texto in FUERA:
            return None
    for texto in [ciudad] + partes:
        if not texto or texto in SOLO_PAIS:
            continue
        for alias, nombre in _CIUDADES_ORDEN:
            if _contiene(texto, alias):
                return nombre
    if partes or (ciudad and ciudad not in SOLO_PAIS):
        return None
    return SIN_ESPECIFICAR


def sueldo(job):
    for k in ("job_salary_string", "job_salary"):
        if job.get(k):
            return str(job[k]).strip()
    mn, mx = job.get("job_min_salary"), job.get("job_max_salary")
    if not mn and not mx:
        return None
    f = lambda v: f"${v:,.0f}"
    rango = f"{f(mn)} – {f(mx)}" if mn and mx and mn != mx else f(mn or mx)
    periodo = PERIODOS.get(str(job.get("job_salary_period") or "").upper(), "")
    return (rango + " " + periodo).strip()


def fecha_publicacion(job):
    iso = job.get("job_posted_at_datetime_utc")
    ts = job.get("job_posted_at_timestamp")
    try:
        if iso:
            d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        elif ts:
            d = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        else:
            return job.get("job_posted_at")
        return d.astimezone(TZ).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError):
        return job.get("job_posted_at")


def extracto(texto):
    t = " ".join(str(texto or "").split())
    if len(t) <= LARGO_EXTRACTO:
        return t
    return t[:LARGO_EXTRACTO].rsplit(" ", 1)[0] + "…"


def liga_limpia(url):
    if not url:
        return ""
    p = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), urllib.parse.urlencode(q), ""))


def convertir(job, consulta):
    remoto = es_remoto(job)
    estado = zona(job)
    if estado == SIN_ESPECIFICAR:
        ubic = SIN_ESPECIFICAR
    else:
        ubic = lugar(job) or ", ".join(x for x in (job.get("job_city"), job.get("job_state")) if x) or None
    return {
        "puesto": (job.get("job_title") or "").strip(),
        "empresa": (job.get("employer_name") or "").strip(),
        "ubicacion": ubic,
        "estado": estado,
        "modalidad": "remoto" if remoto else "no remoto",
        "sueldo": sueldo(job),
        "fecha_publicacion": fecha_publicacion(job),
        "portal": job.get("job_publisher"),
        "liga": job.get("job_apply_link"),
        "extracto": extracto(job.get("job_description")),
        "busquedas": [consulta],
    }


class Deduplicador:
    """Mismo puesto y empresa, o misma liga = la misma vacante."""

    def __init__(self):
        self.lista, self.por_clave = [], {}

    def agregar(self, v):
        claves = []
        if norm(v["puesto"]) and norm(v["empresa"]) not in ("", "confidencial", "empresa confidencial"):
            claves.append("pe:" + norm(v["puesto"]) + "|" + norm(v["empresa"]))
        if liga_limpia(v["liga"]):
            claves.append("liga:" + liga_limpia(v["liga"]))
        previa = next((self.por_clave[k] for k in claves if k in self.por_clave), None)
        if previa is not None:
            for b in v["busquedas"]:
                if b not in previa["busquedas"]:
                    previa["busquedas"].append(b)
            return False
        for k in claves:
            self.por_clave[k] = v
        self.lista.append(v)
        return True


def descartada(job):
    """Lo necesario para revisar por qué se descartó una vacante."""
    return {
        "puesto": (job.get("job_title") or "").strip(),
        "empresa": (job.get("employer_name") or "").strip(),
        "ubicacion": lugar_completo(job) or None,
        "ciudad": job.get("job_city"),
        "estado": job.get("job_state"),
        "pais": job.get("job_country"),
        "portal": job.get("job_publisher"),
    }


def resumen_portales(vacantes):
    conteo = {}
    for v in vacantes:
        conteo[v["portal"] or "desconocido"] = conteo.get(v["portal"] or "desconocido", 0) + 1
    return dict(sorted(conteo.items(), key=lambda x: (-x[1], x[0])))


# ---------- Portal del Empleo (STPS) ----------
# El buscador de la portada pide hCaptcha; no se usa. Las páginas públicas por estado
# (www.empleo.gob.mx/vacantes/hidalgo) cargan sus vacantes de un endpoint JSON, ordenadas de la más
# nueva a la más vieja. Ese endpoint rechaza (403) a los clientes que no son navegador, por eso se llama
# desde Chromium headless (Playwright), sin cambiarle la identidad. Se pide con «que» vacío, igual que
# esas páginas, y los términos se filtran aquí. Nunca se consulta la búsqueda de candidatos.
# Términos de uso (empleo.gob.mx/politicas): uso personal y no comercial; al reproducir hay que citar
# la dirección y la fecha de consulta (sección 10), por eso se guardan en «portal_empleo».
PORTAL = "Portal del Empleo"
PORTAL_URL = "https://www.empleo.gob.mx"
PORTAL_API = "/api/Login/busqueda/empleos"
PORTAL_ENTIDADES = [("9", "Ciudad de México"), ("15", "Estado de México"), ("13", "Hidalgo"),
                    ("29", "Tlaxcala"), ("21", "Puebla")]
PORTAL_TERMINOS = {  # término -> expresión sobre el título normalizado
    "analista": r"\banalist",
    "contable": r"\bcontables?\b",
    "contabilidad": r"\bcontabilidad\b",
    "finanzas": r"\bfinanzas\b",
    "presupuesto": r"\bpresupuest",
    "auxiliar administrativo": r"\baux(iliar|ilar)?( de)? administra(tiv|cion)",
}
PORTAL_MAX_PETICIONES = 30   # contando la carga de la página
PORTAL_PAUSA = 2             # segundos entre peticiones
PORTAL_POR_PAGINA = 50       # lo mismo que piden las páginas del portal
PORTAL_DIAS = 3
_PORTAL_FETCH = """async (cuerpo) => {
  const r = await fetch('%s', {method: 'POST', body: JSON.stringify(cuerpo),
    headers: {'Content-Type': 'application/json', 'Accept': 'application/json, text/plain, */*'}});
  return {status: r.status, texto: await r.text()};
}""" % PORTAL_API


def portal_terminos(titulo):
    t = norm(titulo)
    return [termino for termino, patron in PORTAL_TERMINOS.items() if re.search(patron, t)]


def portal_fecha(item):
    f = str(item.get("fechaPublicacion") or "")[:10]  # «2026-11-18T00:00:00.000+00:00»: es la fecha, no la hora
    return f if re.fullmatch(r"\d{4}-\d{2}-\d{2}", f) else SIN_ESPECIFICAR


def portal_sueldo(item):
    mn, mx = item.get("salarioOfrecido") or 0, item.get("salarioOfrecidoMaximo") or 0
    if not mn and not mx:
        return None
    rango = f"${mn:,.0f} – ${mx:,.0f}" if mn and mx and mx > mn else f"${(mn or mx):,.0f}"
    return rango + " al mes"


def portal_liga(item):
    titulo = urllib.parse.quote(str(item.get("tituloOferta") or "").strip().upper().replace(" ", "-"), safe="-()")
    return f"{PORTAL_URL}/puesto-de-trabajo/vacante/{item['id']}-{titulo}"


def portal_convertir(item, estado, terminos):
    titulo = " ".join(str(item.get("tituloOferta") or "").split())
    descripcion = str(item.get("descripcion") or "")
    remoto = any(norm(p) in norm(titulo + " " + descripcion) for p in PALABRAS_REMOTO)
    empresa = (item.get("nombreEmpresa") or "").strip() or ("Confidencial" if item.get("confidencial") else "")
    municipio = (item.get("municipio") or item.get("ciudad") or "").strip()
    return {
        "puesto": titulo,
        "empresa": empresa,
        "ubicacion": ", ".join(x for x in (municipio, estado) if x),
        "estado": estado,
        "modalidad": "remoto" if remoto else "no remoto",
        "sueldo": portal_sueldo(item),
        "fecha_publicacion": portal_fecha(item),
        "portal": PORTAL,
        "liga": portal_liga(item),
        "extracto": extracto(descripcion),
        "busquedas": terminos,
    }


def buscar_portal_empleo(hoy, errores):
    """Devuelve (vacantes, resumen). Nunca lanza excepciones: los problemas van a «errores»."""
    corte = (hoy - timedelta(days=PORTAL_DIAS)).strftime("%Y-%m-%d")
    resumen = {"url": PORTAL_URL, "consultado": hoy.isoformat(timespec="seconds"), "publicadas_desde": corte,
               "terminos": list(PORTAL_TERMINOS), "peticiones": 0, "por_estado": []}
    vacantes = []

    def error(texto):
        print(f"[{PORTAL}] {texto}")
        errores.append({"fuente": PORTAL, "error": texto[:300]})

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        error("Playwright no está instalado; se omite el Portal del Empleo.")
        return vacantes, resumen
    estados = [{"entidad": e, "estado": n, "pagina": 0, "terminado": False,
                "paginas": 0, "revisadas": 0, "recientes": 0, "coinciden": 0} for e, n in PORTAL_ENTIDADES]
    try:
        with sync_playwright() as pw:
            navegador = pw.chromium.launch()
            try:
                pagina = navegador.new_page()
                resumen["peticiones"] += 1
                pagina.goto(PORTAL_URL + "/api/version", timeout=60000)  # página mínima del mismo sitio
                bloqueado = False
                while not bloqueado and resumen["peticiones"] < PORTAL_MAX_PETICIONES:
                    pendientes = [e for e in estados if not e["terminado"]]
                    if not pendientes:
                        break
                    for e in pendientes:  # por turnos, para que ningún estado se lleve todas las peticiones
                        if resumen["peticiones"] >= PORTAL_MAX_PETICIONES:
                            break
                        time.sleep(PORTAL_PAUSA)
                        resumen["peticiones"] += 1
                        cuerpo = {"que": None, "donde": {"entidad": e["entidad"]}, "items": PORTAL_POR_PAGINA,
                                  "page": e["pagina"], "orden": "fecha_publicacion desc", "filter": {}}
                        try:
                            r = pagina.evaluate(_PORTAL_FETCH, cuerpo)
                        except Exception as ex:
                            error(f"{e['estado']}, página {e['pagina'] + 1}: {ex}")
                            e["terminado"] = True
                            continue
                        if r["status"] in (401, 403, 429):
                            error(f"El portal rechazó la consulta (HTTP {r['status']}): {r['texto'][:120]}")
                            bloqueado = True
                            break
                        try:
                            datos = json.loads(r["texto"]) if r["status"] == 200 else None
                            items = datos["content"]
                            assert isinstance(items, list) and all("id" in i and "tituloOferta" in i for i in items)
                        except Exception:
                            error(f"{e['estado']}: respuesta inesperada (HTTP {r['status']}); el portal pudo cambiar. "
                                  f"{str(r.get('texto'))[:120]}")
                            e["terminado"] = True
                            continue
                        e["paginas"] += 1
                        e["revisadas"] += len(items)
                        fechas = []
                        for item in items:
                            fecha = portal_fecha(item)
                            if fecha != SIN_ESPECIFICAR:
                                fechas.append(fecha)
                                if fecha < corte:
                                    continue
                            e["recientes"] += 1
                            terminos = portal_terminos(item.get("tituloOferta"))
                            if terminos:
                                e["coinciden"] += 1
                                vacantes.append(portal_convertir(item, e["estado"], terminos))
                        e["pagina"] += 1
                        if not items or datos.get("last", True) or (fechas and min(fechas) < corte):
                            e["terminado"] = True
            finally:
                navegador.close()
    except Exception as ex:  # el navegador no arrancó, la página no cargó, etc.
        error(f"{type(ex).__name__}: {ex}")
    for e in estados:
        incompleto = not e["terminado"]
        resumen["por_estado"].append({"estado": e["estado"], "paginas": e["paginas"], "revisadas": e["revisadas"],
                                      "recientes": e["recientes"], "coinciden": e["coinciden"],
                                      **({"incompleto": True} if incompleto and e["paginas"] else {})})
    print(f"[{PORTAL}] {resumen['peticiones']} peticiones, {len(vacantes)} vacantes con los términos")
    return vacantes, resumen


def main():
    hoy = ahora()
    dia = hoy.strftime("%Y-%m-%d")
    codigo, errores, detalle = 0, [], []

    dedup = Deduplicador()
    archivo_dia = CARPETA / f"{dia}.json"
    previo = {}
    descartadas, vistas = [], set()

    def descartar(d):
        clave = norm(d["puesto"]) + "|" + norm(d["empresa"]) + "|" + norm(d["ubicacion"])
        if clave not in vistas:
            vistas.add(clave)
            descartadas.append(d)

    if archivo_dia.exists():  # segunda ejecución del mismo día: se combinan los resultados
        previo = json.loads(archivo_dia.read_text(encoding="utf-8"))
        for v in previo.get("vacantes", []):
            dedup.agregar(v)
        for d in previo.get("descartadas_detalle", []):
            descartar(d)

    # ---- JSearch ----
    clave = os.environ.get("JSEARCH_API_KEY", "").strip()
    uso = leer_uso(hoy)
    disponibles = quedan(uso) if clave else 0
    if not clave:
        msg = "Falta el secreto JSEARCH_API_KEY. Agrégalo en Settings > Secrets and variables > Actions."
        print(msg)
        errores.append({"fuente": "JSearch", "error": msg})
        codigo = 1
    elif disponibles == 0:
        print(f"JSearch: límite alcanzado ({uso['consultas_dia']}/{LIMITE_DIA} hoy, "
              f"{uso['consultas_mes']}/{LIMITE_MES} este mes). No se consulta la API.")
    for consulta in CONSULTAS[:disponibles]:
        uso["consultas_dia"] += 1
        uso["consultas_mes"] += 1
        uso["historial"][dia] = uso["historial"].get(dia, 0) + 1
        guardar_uso(uso)  # se cuenta antes de enviar: el límite del mes nunca se rebasa
        try:
            trabajos = buscar(consulta, clave)
        except ErrorClave as e:
            print(f"[{consulta}] {e}")
            detalle.append({"consulta": consulta, "error": str(e)[:200]})
            errores.append({"fuente": "JSearch", "error": str(e)[:300]})
            codigo = 1
            break
        except Exception as e:  # red, tiempo de espera, JSON inválido
            print(f"[{consulta}] error: {e}")
            detalle.append({"consulta": consulta, "error": str(e)[:200]})
            errores.append({"fuente": "JSearch", "error": f"{consulta}: {str(e)[:250]}"})
            continue
        en_zona = nuevas = 0
        for job in trabajos:
            pais = (job.get("job_country") or "").upper()
            if not es_remoto(job) and (pais not in ("", "MX") or zona(job) is None):  # las remotas pasan siempre
                descartar(descartada(job))
                continue
            en_zona += 1
            nuevas += dedup.agregar(convertir(job, consulta))
        detalle.append({"consulta": consulta, "encontradas": len(trabajos), "en_zona_o_remotas": en_zona, "nuevas": nuevas})
        print(f"[{consulta}] {len(trabajos)} encontradas, {en_zona} en la zona, remotas o sin especificar, {nuevas} nuevas")
        time.sleep(1)
    guardar_uso(uso)

    # ---- Portal del Empleo: si falla, queda en «errores» y el resto sigue ----
    try:
        del_portal, resumen_portal = buscar_portal_empleo(hoy, errores)
    except Exception as e:  # por si acaso; buscar_portal_empleo ya atrapa sus errores
        errores.append({"fuente": PORTAL, "error": f"{type(e).__name__}: {str(e)[:250]}"})
        del_portal, resumen_portal = [], {}
    nuevas_portal = sum(dedup.agregar(v) for v in del_portal)
    if resumen_portal:
        resumen_portal["nuevas"] = nuevas_portal

    jsearch_ok = any("error" not in d for d in detalle)
    portal_ok = any(e.get("paginas") for e in resumen_portal.get("por_estado", []))
    vacantes = dedup.lista
    por_ubicacion = {}
    for d in descartadas:
        donde = d["ubicacion"] or "sin ubicación"
        por_ubicacion[donde] = por_ubicacion.get(donde, 0) + 1
    sin_especificar = sum(v["estado"] == SIN_ESPECIFICAR for v in vacantes)
    salida = {
        "fecha": dia,
        "generado": hoy.isoformat(timespec="seconds"),
        "pais": PAIS,
        "publicadas": PUBLICADAS,
        "consultas": previo.get("consultas", []) + detalle,
        "portal_empleo": resumen_portal or previo.get("portal_empleo"),
        "errores": errores,
        "total": len(vacantes),
        "sin_especificar": sin_especificar,
        "por_portal": resumen_portales(vacantes),
        "descartadas": len(descartadas),
        "descartadas_por_ubicacion": dict(sorted(por_ubicacion.items(), key=lambda x: (-x[1], x[0]))),
        "descartadas_detalle": descartadas,
        "vacantes": vacantes,
    }
    if jsearch_ok or portal_ok:  # si todo falló, no se tocan los resultados anteriores
        CARPETA.mkdir(exist_ok=True)
        texto = json.dumps(salida, ensure_ascii=False, indent=2) + "\n"
        archivo_dia.write_text(texto, encoding="utf-8")
        (CARPETA / "latest.json").write_text(texto, encoding="utf-8")
    else:
        print("Ninguna fuente respondió; no se modifican los resultados.")

    resumen = (f"## Vacantes del {dia}\n\n**{len(vacantes)}** vacantes en la zona, remotas o sin especificar "
               f"({sin_especificar} sin especificar) · {len(descartadas)} descartadas por ubicación · "
               f"consultas JSearch: {uso['consultas_dia']}/{LIMITE_DIA} hoy, {uso['consultas_mes']}/{LIMITE_MES} este mes · "
               f"{PORTAL}: {nuevas_portal} nuevas en {resumen_portal.get('peticiones', 0)} peticiones\n\n"
               + "\n".join(f"- {p}: {n}" for p, n in salida["por_portal"].items()) + "\n"
               + "".join(f"\n> ⚠️ {e['fuente']}: {e['error']}" for e in errores) + "\n")
    print(resumen)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(resumen)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
