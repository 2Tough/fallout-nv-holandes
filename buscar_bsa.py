#!/usr/bin/env python3
"""
buscar_bsa.py
Busca textos dentro de los archivos .bsa del juego (solo en .xml, .txt y similares)
y extrae los que interesen.

Uso (desde FNV_NL):
  python buscar_bsa.py buscar  "<carpeta Data>" "Stain-resistant" "Points to go"
  python buscar_bsa.py extraer "<carpeta Data>" "menus\\...\\archivo.xml"    -> lo copia a FNV_NL\\extraidos\\
"""

import sys
from pathlib import Path

from voces_fnv import ArchivoBSA, ErrorFatal

EXTENSIONES = (".xml", ".txt", ".csv", ".ini", ".lst", ".cfg")
CARPETA = Path(__file__).resolve().parent


def bsas(data):
    data = Path(data)
    if not data.is_dir():
        raise ErrorFatal(f"No encuentro la carpeta {data}")
    lista = sorted(data.glob("*.bsa"))
    if not lista:
        raise ErrorFatal(f"No hay archivos .bsa en {data}")
    return lista


def comando_buscar(data, textos):
    textos_b = [(t, t.lower().encode("cp1252", errors="ignore")) for t in textos]
    encontrados = 0
    for ruta in bsas(data):
        try:
            bsa = ArchivoBSA(ruta)
        except ErrorFatal as e:
            print(f"  {ruta.name}: {e}")
            continue
        candidatos = [r for r in bsa.archivos if r.endswith(EXTENSIONES)]
        print(f"{ruta.name}: {len(candidatos)} archivos de texto")
        for interna in candidatos:
            try:
                datos = bsa.extraer(interna).lower()
            except Exception:
                continue
            hallados = [t for t, tb in textos_b if tb and tb in datos]
            if hallados:
                encontrados += 1
                print(f"   -> {interna}   ({', '.join(hallados)})")
    for ruta in sorted(Path(data).rglob("*")):
        if ruta.suffix.lower() in EXTENSIONES and ruta.is_file():
            datos = ruta.read_bytes().lower()
            hallados = [t for t, tb in textos_b if tb and tb in datos]
            if hallados:
                encontrados += 1
                print(f"   -> archivo suelto: {ruta}   ({', '.join(hallados)})")
    print(f"\n{encontrados} archivos encontrados.\n")


def comando_extraer(data, interna):
    for ruta in bsas(data):
        bsa = ArchivoBSA(ruta)
        if interna.lower() in bsa.archivos:
            destino = CARPETA / "extraidos" / Path(*interna.lower().split("\\"))
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(bsa.extraer(interna))
            print(f"\nExtraído de {ruta.name} a:\n  {destino}\n")
            return
    raise ErrorFatal(f"No encontré {interna} en ningún .bsa")


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "buscar":
        comando_buscar(sys.argv[2], sys.argv[3:])
    elif len(sys.argv) == 4 and sys.argv[1] == "extraer":
        comando_extraer(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        main()
    except ErrorFatal as e:
        sys.exit(f"\nError: {e}")
