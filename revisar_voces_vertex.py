#!/usr/bin/env python3
"""
revisar_voces_vertex.py
Para revisar los audios generados con voces_fnv_vertex.py. No usa Gemini ni gasta nada.

  python revisar_voces_vertex.py escuchar BSA VOCES
      Copia a la carpeta escuchar_voces\\ (junto a los scripts), con nombres legibles:
        - dudosos\\     los audios apartados por "demasiado largo" (los de voces_problemas.csv)
        - con_estilo\\  una muestra de audios hechos con Vertex que llevaban estilo (emoción) y
                       pasaron la comprobación: ahí se oye si leyó "Say in this style..."
        - sin_estilo\\  una muestra sin estilo, para comparar
      Y dice cuántos audios de Vertex con estilo hay en la caché.

  python revisar_voces_vertex.py apartar BSA VOCES
      Mueve los audios de Vertex CON estilo (generados con el formato antiguo, que se leía) a
      cache_voces\\_apartados_vertex\\ y borra sus .ogg de salida_voces, para que el próximo
      'generar' los vuelva a hacer con el formato nuevo. No borra nada de la caché: se puede deshacer
      con 'devolver'.

  python revisar_voces_vertex.py devolver
      Deshace 'apartar' (vuelve a poner los audios en la caché; luego 'generar ... --rehacer').

Opciones: --desde 2026-11-08  (solo audios generados desde esa fecha = los de Vertex)
          --muestra 15        (cuántos copiar a con_estilo y sin_estilo)

BSA y VOCES son las mismas rutas que en 'generar'.
"""

import argparse
import datetime
import hashlib
import re
import shutil
import sys
from pathlib import Path

import voces_fnv as base
import voces_fnv_vertex  # noqa: F401  (acepta también las voces de los DLC)
from voces_fnv import ErrorFatal

CARPETA_ESCUCHAR = base.CARPETA / "escuchar_voces"
CARPETA_APARTADOS = base.CARPETA_CACHE / "_apartados_vertex"
CARPETA_DUDOSOS = base.CARPETA_CACHE / "_dudosos"


def clave_de(modelo, voz, estilo, texto):
    return hashlib.sha1(f"{modelo}|{voz}|{estilo}|{texto}".encode()).hexdigest()[:24]


def ruta_cache(clave):
    return base.CARPETA_CACHE / clave[:2] / f"{clave}.wav"


def nombre(texto, largo=40):
    return re.sub(r"[^\w]+", "_", texto, flags=re.UNICODE).strip("_")[:largo].rstrip("_") or "frase"


def trabajos(cfg, ruta_bsa, ruta_voces):
    """clave -> datos del audio, igual que los agrupa 'generar'."""
    tipos_cfg = base.leer_json(base.ARCHIVO_TIPOS, {}).get("tipos", {})
    if not tipos_cfg:
        raise ErrorFatal("No existe voces_tipos.json.")
    _, _, _, emparejados, _, _ = base.emparejar(ruta_bsa, ruta_voces, None, None)
    res = {}
    for ruta, tipo, linea, texto in emparejados:
        t = tipos_cfg.get(tipo)
        if not t or not t.get("voz"):
            continue
        estilo = base.estilo_de(linea, t)
        modelo = base.modelo_de(tipo, t, cfg)
        c = clave_de(modelo, t["voz"], estilo, texto)
        j = res.setdefault(c, {"texto": texto, "estilo": estilo, "tipo": tipo, "voz": t["voz"],
                               "modelo": modelo, "destinos": []})
        j["destinos"].append(base.CARPETA_SALIDA / Path(*ruta.split("\\")).with_suffix(".ogg"))
    return res


def de_vertex(clave, desde):
    r = ruta_cache(clave)
    return r.exists() and r.stat().st_mtime >= desde


def copiar(origen, carpeta, j, clave, segundos=None):
    carpeta.mkdir(parents=True, exist_ok=True)
    extra = f"__{nombre(j['estilo'], 25)}" if j["estilo"] else ""
    destino = carpeta / f"{j['tipo']}__{nombre(j['texto'])}{extra}__{clave[:6]}.wav"
    shutil.copy2(origen, destino)
    return destino


def comando_escuchar(cfg, bsa, voces, desde, muestra):
    todos = trabajos(cfg, bsa, voces)
    if CARPETA_ESCUCHAR.exists():
        shutil.rmtree(CARPETA_ESCUCHAR)
    n_dudosos = 0
    for c, j in todos.items():
        d = CARPETA_DUDOSOS / f"{c}.wav"
        if d.exists() and not ruta_cache(c).exists():
            copiar(d, CARPETA_ESCUCHAR / "dudosos", j, c)
            n_dudosos += 1
    con = [(c, j) for c, j in todos.items() if j["estilo"] and de_vertex(c, desde)]
    sin = [(c, j) for c, j in todos.items() if not j["estilo"] and de_vertex(c, desde)]
    paso = max(1, len(con) // max(1, muestra))       # repartidos por todo el juego, no solo el principio
    for c, j in con[::paso][:muestra]:
        copiar(ruta_cache(c), CARPETA_ESCUCHAR / "con_estilo", j, c)
    paso = max(1, len(sin) // max(1, muestra))
    for c, j in sin[::paso][:muestra]:
        copiar(ruta_cache(c), CARPETA_ESCUCHAR / "sin_estilo", j, c)
    print(f"\nAudios en caché generados desde {datetime.date.fromtimestamp(desde)}: {len(con) + len(sin):,}")
    print(f"   con estilo (emoción): {len(con):,}   <- los sospechosos de leer 'Say in this style...'")
    print(f"   sin estilo:           {len(sin):,}")
    print(f"\nCopiados a {CARPETA_ESCUCHAR}:")
    print(f"   dudosos\\     {n_dudosos}  (apartados por demasiado largos)")
    print(f"   con_estilo\\  {min(muestra, len(con))}  (el nombre lleva el estilo que se pidió)")
    print(f"   sin_estilo\\  {min(muestra, len(sin))}  (para comparar)")
    print("\nSi en con_estilo se oye la instrucción en inglés, ejecuta 'apartar' y luego 'generar'.\n")


def comando_apartar(cfg, bsa, voces, desde):
    todos = trabajos(cfg, bsa, voces)
    con = [(c, j) for c, j in todos.items() if j["estilo"] and de_vertex(c, desde)]
    if not con:
        print("\nNo hay audios de Vertex con estilo en la caché. Nada que apartar.\n")
        return
    CARPETA_APARTADOS.mkdir(parents=True, exist_ok=True)
    segundos = 0.0
    oggs = 0
    for c, j in con:
        origen = ruta_cache(c)
        segundos += base.duracion_wav(origen.read_bytes())[0]
        shutil.move(str(origen), str(CARPETA_APARTADOS / origen.name))
        for ogg in j["destinos"]:
            if ogg.exists():
                ogg.unlink()
                oggs += 1
    precio_medio = sum(base.precio(j["modelo"], cfg) for _, j in con) / len(con)
    coste = segundos * base.TOKENS_POR_SEGUNDO * precio_medio / 1e6
    print(f"\n{len(con):,} audios apartados en {CARPETA_APARTADOS.name}\\ y {oggs:,} .ogg borrados de salida_voces.")
    print(f"Rehacerlos costará aprox. {coste:.2f} USD (algo menos: ya no llevarán la instrucción leída).")
    print("Siguiente: python voces_fnv_vertex.py generar BSA VOCES --max-dolares 80\n")


def comando_devolver():
    if not CARPETA_APARTADOS.exists():
        print("\nNo hay nada apartado.\n")
        return
    n = 0
    for wav in CARPETA_APARTADOS.glob("*.wav"):
        destino = ruta_cache(wav.stem)
        destino.parent.mkdir(parents=True, exist_ok=True)
        if not destino.exists():
            shutil.move(str(wav), str(destino))
            n += 1
    print(f"\n{n:,} audios devueltos a la caché. Para rehacer sus .ogg: generar ... --rehacer\n")


def main():
    p = argparse.ArgumentParser(description="Revisar los audios de Vertex de New Vegas (sin coste).")
    sub = p.add_subparsers(dest="comando", required=True)
    for n in ("escuchar", "apartar"):
        s = sub.add_parser(n)
        s.add_argument("bsa", type=Path)
        s.add_argument("voces", type=Path)
        s.add_argument("--desde", default="2026-11-08", help="fecha (AAAA-MM-DD) desde la que se usó Vertex")
        if n == "escuchar":
            s.add_argument("--muestra", type=int, default=15)
    sub.add_parser("devolver")
    a = p.parse_args()
    cfg = base.leer_config()
    try:
        if a.comando == "devolver":
            comando_devolver()
            return
        desde = datetime.datetime.fromisoformat(a.desde).timestamp()
        if a.comando == "escuchar":
            comando_escuchar(cfg, a.bsa, a.voces, desde, a.muestra)
        else:
            comando_apartar(cfg, a.bsa, a.voces, desde)
    except ErrorFatal as e:
        sys.exit(f"\nError: {e}")


if __name__ == "__main__":
    main()
