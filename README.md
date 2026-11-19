# Vacantes diarias

Busca vacantes de finanzas, contabilidad y presupuesto en México con la API
[JSearch de OpenWeb Ninja](https://www.openwebninja.com/api/jsearch) (que lee Google for Jobs:
LinkedIn, Indeed, Glassdoor, OCC, Computrabajo, etc.) y guarda las que están en Ciudad de México,
Estado de México, Hidalgo, Tlaxcala, Puebla, son remotas o no dicen dónde.

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

## Límites

Máximo **9 consultas por día y 190 al mes**. La cuenta está en [`uso.json`](uso.json); cada
consulta se cuenta antes de enviarse y, al llegar al límite, el script ya no llama a la API.
Al correrlo a mano se puede marcar **ignorar_limite_dia** para volver a buscar el mismo día;
el límite del mes se respeta siempre.

## Configuración

La clave de la API va en el secreto del repositorio `JSEARCH_API_KEY`
(Settings › Secrets and variables › Actions). No está en el código.
