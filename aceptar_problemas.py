#!/usr/bin/env python3
"""
aceptar_problemas.py
Acepta en la caché (cache_traducciones.json) las traducciones de un *_problemas.csv de
traducir_fnv.py que en realidad están bien. Así exportar-xedit las incluye.

Por defecto solo acepta las filas con motivo "saltos de línea distintos": son traducciones
correctas en las que Gemini juntó o separó líneas. NUNCA acepta "sin traducir", porque esa
respuesta es el mismo texto en inglés.

Uso (desde FNV_NL):
  python aceptar_problemas.py WildCard_en_de_problemas.csv            (muestra qué aceptaría)
  python aceptar_problemas.py WildCard_en_de_problemas.csv --aplicar  (lo guarda en la caché)
  --todos   acepta también los demás motivos (salvo "sin traducir")

Antes de guardar hace una copia: cache_traducciones.json.bak
"""

import csv
import json
import shutil
import sys
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
CACHE = CARPETA / "cache_traducciones.json"


def main():
    args = sys.argv[1:]
    aplicar = "--aplicar" in args
    todos = "--todos" in args
    rutas = [a for a in args if not a.startswith("--")]
    if not rutas:
        print(__doc__)
        return
    ruta_csv = Path(rutas[0])
    if not ruta_csv.exists():
        sys.exit(f"No encuentro {ruta_csv}")
    if not CACHE.exists():
        sys.exit(f"No encuentro {CACHE}")

    with open(ruta_csv, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.reader(f, delimiter=";"))
    cabecera, filas = filas[0], filas[1:]
    i_motivo = cabecera.index("motivo")
    i_orig = cabecera.index("original")
    i_resp = len(cabecera) - 1          # la última columna es la respuesta del traductor

    with open(CACHE, encoding="utf-8") as f:
        cache = json.load(f)

    aceptadas, saltadas = 0, 0
    for fila in filas:
        if len(fila) <= i_resp:
            continue
        motivo, original, respuesta = fila[i_motivo], fila[i_orig], fila[i_resp]
        corto = original.replace("\n", " ")[:70]
        if "sin traducir" in motivo or not respuesta.strip() or respuesta.strip() == original.strip():
            print(f"  NO  ({motivo}): {corto}")
            saltadas += 1
            continue
        if not todos and "saltos de línea" not in motivo:
            print(f"  NO  ({motivo}; usa --todos para aceptarlo): {corto}")
            saltadas += 1
            continue
        print(f"  SÍ  ({motivo}): {corto}")
        cache[original] = respuesta
        aceptadas += 1

    print(f"\nAceptadas: {aceptadas}   No aceptadas: {saltadas}")
    if not aplicar:
        print("No he cambiado nada. Para guardarlas en la caché, repite el comando con --aplicar\n")
        return
    if aceptadas:
        shutil.copy2(CACHE, CACHE.with_name(CACHE.name + ".bak"))
        tmp = CACHE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        tmp.replace(CACHE)
        print(f"Guardado en {CACHE.name} (copia anterior: {CACHE.name}.bak)\n")


if __name__ == "__main__":
    main()
