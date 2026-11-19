#!/usr/bin/env python3
"""Busca vacantes en JSearch (OpenWeb Ninja) y guarda las de la zona centro de México o remotas.

Documentación de la API: https://www.openwebninja.com/api/jsearch
Especificación usada:   https://openwebninja.s3.us-east-1.amazonaws.com/portal/openapi/jsearch.yaml
  GET https://api.openwebninja.com/jsearch/search-v2, encabezado x-api-key.
  Cada página (hasta 10 vacantes) consume un crédito, por eso num_pages = 1.

La clave se lee de la variable de entorno JSEARCH_API_KEY (secreto de GitHub). Solo usa la biblioteca estándar.
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
from datetime import datetime, timezone
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


# Nombres y abreviaturas con que Google for Jobs escribe cada estado (ya normalizados).
ESTADOS = {
    "Ciudad de México": {"ciudad de mexico", "cdmx", "mexico city", "distrito federal", "df", "d f",
                         "cd de mexico", "cd mexico", "mexico df", "mexico d f", "ciudad de mexico cdmx"},
    "Estado de México": {"estado de mexico", "state of mexico", "mexico state", "edo de mexico",
                         "edo de mex", "edo mex", "edomex", "mex"},
    "Hidalgo": {"hidalgo", "hgo"},
    "Tlaxcala": {"tlaxcala", "tlax"},
    "Puebla": {"puebla", "pue"},
}
# Ciudades y alcaldías comunes, para cuando el estado no viene.
CIUDADES = {
    "Ciudad de México": {"ciudad de mexico", "cdmx", "mexico city", "alvaro obregon", "azcapotzalco",
                         "benito juarez", "coyoacan", "cuajimalpa", "cuajimalpa de morelos", "cuauhtemoc",
                         "gustavo a madero", "iztacalco", "iztapalapa", "magdalena contreras",
                         "la magdalena contreras", "miguel hidalgo", "milpa alta", "tlahuac", "tlalpan",
                         "venustiano carranza", "xochimilco", "santa fe", "polanco"},
    "Estado de México": {"toluca", "toluca de lerdo", "naucalpan", "naucalpan de juarez", "tlalnepantla",
                         "tlalnepantla de baz", "ecatepec", "ecatepec de morelos", "nezahualcoyotl",
                         "ciudad nezahualcoyotl", "atizapan", "atizapan de zaragoza", "cuautitlan",
                         "cuautitlan izcalli", "huixquilucan", "interlomas", "metepec", "texcoco",
                         "tultitlan", "coacalco", "chalco", "ixtapaluca", "nicolas romero", "tecamac",
                         "zumpango", "lerma", "chimalhuacan", "valle de chalco", "zinacantepec",
                         "tultepec", "huehuetoca", "tepotzotlan", "ocoyoacac", "san mateo atenco"},
    "Hidalgo": {"pachuca", "pachuca de soto", "mineral de la reforma", "tulancingo",
                "tulancingo de bravo", "tula de allende", "tizayuca", "huejutla", "actopan",
                "ixmiquilpan", "tepeji del rio", "tepeji del rio de ocampo", "ciudad sahagun"},
    "Tlaxcala": {"tlaxcala", "tlaxcala de xicohtencatl", "apizaco", "huamantla",
                 "chiautempan", "zacatelco", "tlaxco"},
    "Puebla": {"puebla", "heroica puebla de zaragoza", "san andres cholula", "san pedro cholula",
               "cholula", "atlixco", "tehuacan", "san martin texmelucan", "huauchinango", "teziutlan",
               "cuautlancingo", "amozoc"},
}
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


def quedan(uso):
    return max(0, min(LIMITE_DIA - uso["consultas_dia"], LIMITE_MES - uso["consultas_mes"]))


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
def es_remoto(job):
    if job.get("job_is_remote"):
        return True
    texto = norm(" ".join(str(job.get(k) or "") for k in ("job_title", "job_location", "job_city")))
    return any(norm(p) in texto for p in PALABRAS_REMOTO)


def zona(job):
    """Devuelve el estado de la zona (CDMX, Edomex, Hidalgo, Tlaxcala, Puebla) o None."""
    estado, ciudad = norm(job.get("job_state")), norm(job.get("job_city"))
    for nombre, alias in ESTADOS.items():
        if estado in alias:
            return nombre
    for nombre, ciudades in CIUDADES.items():
        if ciudad in ciudades:
            return nombre
    partes = [norm(p) for p in str(job.get("job_location") or "").split(",") if norm(p)]
    for parte in reversed(partes[1:]):  # "Toluca de Lerdo, Méx." -> "mex"
        for nombre, alias in ESTADOS.items():
            if parte in alias:
                return nombre
    if estado == "mexico" and ciudad:  # estado "México" con ciudad: es el Estado de México
        return "Estado de México"
    return None


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
    ubic = job.get("job_location") or ", ".join(x for x in (job.get("job_city"), job.get("job_state")) if x) or None
    return {
        "puesto": (job.get("job_title") or "").strip(),
        "empresa": (job.get("employer_name") or "").strip(),
        "ubicacion": ubic,
        "estado": zona(job),
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
        claves = [k for k in ("pe:" + norm(v["puesto"]) + "|" + norm(v["empresa"]),
                              "liga:" + liga_limpia(v["liga"])) if not k.endswith(":") and k != "pe:|"]
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


def resumen_portales(vacantes):
    conteo = {}
    for v in vacantes:
        conteo[v["portal"] or "desconocido"] = conteo.get(v["portal"] or "desconocido", 0) + 1
    return dict(sorted(conteo.items(), key=lambda x: (-x[1], x[0])))


def main():
    hoy = ahora()
    dia = hoy.strftime("%Y-%m-%d")
    clave = os.environ.get("JSEARCH_API_KEY", "").strip()
    if not clave:
        print("Falta el secreto JSEARCH_API_KEY. Agrégalo en Settings > Secrets and variables > Actions.")
        return 1

    uso = leer_uso(hoy)
    disponibles = quedan(uso)
    if disponibles == 0:
        print(f"Límite alcanzado: {uso['consultas_dia']}/{LIMITE_DIA} hoy y {uso['consultas_mes']}/{LIMITE_MES} este mes. No se consulta la API.")
        guardar_uso(uso)
        return 0

    dedup = Deduplicador()
    archivo_dia = CARPETA / f"{dia}.json"
    previo = {}
    if archivo_dia.exists():  # segunda ejecución del mismo día: se combinan los resultados
        previo = json.loads(archivo_dia.read_text(encoding="utf-8"))
        for v in previo.get("vacantes", []):
            dedup.agregar(v)

    detalle, descartadas, codigo = [], {}, 0
    for consulta in CONSULTAS[:disponibles]:
        uso["consultas_dia"] += 1
        uso["consultas_mes"] += 1
        uso["historial"][dia] = uso["historial"].get(dia, 0) + 1
        guardar_uso(uso)  # se cuenta antes de enviar: el límite nunca se rebasa
        try:
            trabajos = buscar(consulta, clave)
        except ErrorClave as e:
            print(f"[{consulta}] {e}")
            detalle.append({"consulta": consulta, "error": str(e)[:200]})
            codigo = 1
            break
        except Exception as e:  # red, tiempo de espera, JSON inválido
            print(f"[{consulta}] error: {e}")
            detalle.append({"consulta": consulta, "error": str(e)[:200]})
            continue
        en_zona = nuevas = 0
        for job in trabajos:
            pais = (job.get("job_country") or "").upper()
            remoto = es_remoto(job)
            if pais not in ("", "MX") or not (remoto or zona(job)):
                lugar = job.get("job_location") or job.get("job_state") or job.get("job_country") or "sin ubicación"
                descartadas[lugar] = descartadas.get(lugar, 0) + 1
                continue
            en_zona += 1
            nuevas += dedup.agregar(convertir(job, consulta))
        detalle.append({"consulta": consulta, "encontradas": len(trabajos), "en_zona_o_remotas": en_zona, "nuevas": nuevas})
        print(f"[{consulta}] {len(trabajos)} encontradas, {en_zona} en la zona o remotas, {nuevas} nuevas")
        time.sleep(1)

    hechas = [d for d in detalle if "error" not in d]
    if not detalle:
        return codigo
    vacantes = dedup.lista
    salida = {
        "fecha": dia,
        "generado": hoy.isoformat(timespec="seconds"),
        "pais": PAIS,
        "publicadas": PUBLICADAS,
        "consultas": previo.get("consultas", []) + detalle,
        "total": len(vacantes),
        "por_portal": resumen_portales(vacantes),
        "descartadas_por_ubicacion": dict(sorted(descartadas.items(), key=lambda x: -x[1])),
        "vacantes": vacantes,
    }
    if hechas:  # si todas fallaron, no se tocan los resultados anteriores
        CARPETA.mkdir(exist_ok=True)
        texto = json.dumps(salida, ensure_ascii=False, indent=2) + "\n"
        archivo_dia.write_text(texto, encoding="utf-8")
        (CARPETA / "latest.json").write_text(texto, encoding="utf-8")

    resumen = (f"## Vacantes del {dia}\n\n**{len(vacantes)}** vacantes en la zona o remotas · "
               f"consultas: {uso['consultas_dia']}/{LIMITE_DIA} hoy, {uso['consultas_mes']}/{LIMITE_MES} este mes\n\n"
               + "\n".join(f"- {p}: {n}" for p, n in salida["por_portal"].items()) + "\n")
    print(resumen)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(resumen)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
