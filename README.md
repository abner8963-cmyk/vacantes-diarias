# Vacantes diarias

Busca vacantes de finanzas, contabilidad y presupuesto en México en dos fuentes y guarda las que
están en Ciudad de México, Estado de México, Hidalgo, Tlaxcala, Puebla, son remotas o no dicen dónde:

1. La API [JSearch de OpenWeb Ninja](https://www.openwebninja.com/api/jsearch), que lee Google for Jobs
   (LinkedIn, Indeed, Glassdoor, OCC, Computrabajo, etc.).
2. El [Portal del Empleo](https://www.empleo.gob.mx) de la STPS (`portal` = «Portal del Empleo»).

## Filtro de ubicación

- No distingue acentos ni mayúsculas y reconoce nombres en español e inglés y abreviaturas
  (CDMX, Mexico City, D.F., Edomex, Méx., State of Mexico, Hgo., Pue., Tlax.) y las principales
  alcaldías y municipios (Texcoco, Ecatepec, Naucalpan, Toluca, Pachuca, Tizayuca, Apan,
  Calpulalpan, Apizaco…).
- Un estado de fuera de la zona descarta aunque la ciudad se llame igual que una de la zona
  («Cuauhtémoc, Chih.», «Hidalgo, N.L.»).
- Las vacantes remotas pasan siempre.
- Si solo dice «México» o no trae ciudad, no se descarta: queda con `ubicacion` y `estado`
  «sin especificar» para decidir a mano.

Corre sola en GitHub Actions de lunes a viernes a las 6:00 a.m. (hora de Ciudad de México) y
también se puede ejecutar a mano desde **Actions › Buscar vacantes › Run workflow**.

## Resultados

- [`resultados/latest.json`](resultados/latest.json): las del último día.
- `resultados/AAAA-MM-DD.json`: el historial por día.

Cada vacante trae: `puesto`, `empresa`, `ubicacion`, `estado`, `modalidad` (remoto / no remoto),
`sueldo` (si viene), `fecha_publicacion`, `portal`, `liga` (para postularse), `extracto` y las
`busquedas` que la encontraron. Se quitan duplicados (mismo puesto y empresa, o misma liga).

Para revisar el filtro, `descartadas_detalle` trae cada vacante descartada con `puesto`, `empresa`,
`ubicacion` (el texto completo de la API), `ciudad`, `estado`, `pais` y `portal`.

## Búsquedas

Una consulta por término, con `country=mx`, `date_posted=3days` y una sola página:
analista presupuestal · analista financiero jr · auxiliar contable · analista contable jr ·
control presupuestal · finanzas públicas · analista de datos financieros ·
recién egresado finanzas · contabilidad gubernamental.

## Portal del Empleo

- El buscador de la portada pide hCaptcha y **no se usa**. Las páginas públicas por estado
  (`/vacantes/hidalgo`, etc.) cargan sus vacantes de un endpoint JSON (`/api/Login/busqueda/empleos`),
  ordenadas de la más nueva a la más vieja. Ese endpoint rechaza a los clientes que no son navegador,
  así que se llama desde Chromium headless (Playwright) con su identidad normal.
- Se piden las 5 entidades por turnos, 50 vacantes por página, hasta llegar a las publicadas hace más
  de 3 días. Máximo **30 peticiones por corrida** (contando la carga de la página) y **2 segundos**
  entre cada una. Nunca se consulta la búsqueda de candidatos.
- Se quedan las que tienen en el título: analista, contable, contabilidad, finanzas, presupuesto o
  auxiliar administrativo. Si una vacante no trae fecha, se guarda con fecha «sin especificar».
- `portal_empleo` registra la dirección y la fecha de consulta (lo piden los términos de uso,
  sección 10), las peticiones hechas y lo revisado por estado.
- Si el portal falla, cambia de formato o Playwright no se instala, el error queda en `errores` y la
  corrida sigue con JSearch.
- Términos de uso: [empleo.gob.mx/politicas](https://www.empleo.gob.mx/politicas) (uso personal y no
  comercial, para buscar empleo). El sitio no tiene `robots.txt`.

## Límites

JSearch: máximo **9 consultas por día y 190 al mes**. La cuenta está en [`uso.json`](uso.json); cada
consulta se cuenta antes de enviarse y, al llegar al límite, el script ya no llama a la API.
Al correrlo a mano se puede marcar **ignorar_limite_dia** para volver a buscar el mismo día;
el límite del mes se respeta siempre.

## Configuración

La clave de la API va en el secreto del repositorio `JSEARCH_API_KEY`
(Settings › Secrets and variables › Actions). No está en el código.
