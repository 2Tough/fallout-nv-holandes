#!/usr/bin/env python3
"""
voces_wildcard.py
Voces en holandés para FNV Wild Card (Mod Organizer 2). Reutiliza todo lo de voces_fnv.py y
voces_fnv_vertex.py: la misma caché (cache_voces), las mismas voces por personaje
(voces_tipos.json), los mismos efectos y la misma conexión con Vertex AI.

No necesita FNVEdit: lee directamente los plugins y los audios del modlist (BSA y archivos sueltos
de cada mod) y el texto holandés de WILDCARD\\traducciones_nl.txt.

Clasifica cada audio de diálogo del modlist:
  A) Juego base / DLC, YA doblado (está en [NL] Stemmen):
       - si un mod cambió la frase inglesa y la traducción holandesa cambió -> se regenera
       - si no -> se queda el audio holandés que ya tienes
  B) Juego base / DLC, SIN doblar todavía (p. ej. DLC pendientes) -> solo con --incluir-oficiales
  C) Diálogos nuevos de mods con audio inglés -> se doblan
  D) Diálogos nuevos de mods SIN audio -> solo se cuentan (quedan con subtítulo)

Los audios nuevos se escriben directamente en el mod de MO2 "[NL] Wild Card Stemmen".
Ponlo DEBAJO de "[NL] Stemmen" en MO2 (más prioridad), para que gane en las frases regeneradas.

Uso (PowerShell, desde FNV_NL; MO2 puede estar abierto para 'contar', cerrado para 'generar'):
  python voces_wildcard.py contar
  python voces_wildcard.py generar --limite 20 --max-dolares 1         (prueba pequeña)
  python voces_wildcard.py generar --max-dolares 10
Opciones:
  --mo2 RUTA              carpeta del modlist (por defecto F:\\Mods\\FWC)
  --perfil NOMBRE         perfil de MO2 (por defecto el seleccionado)
  --carpeta CARP          carpeta con traducciones_nl.txt (por defecto WILDCARD)
  --es CARP               carpeta "Edit Scripts" con voces_nl*.txt (por defecto la del proyecto)
  --solo mods|cambiadas   generar solo una categoría
  --incluir-oficiales     generar también los audios del juego base/DLC que aún no tienen voz holandesa
  --filtro TEXTO ...      solo audios cuya ruta contenga alguno de estos textos (p. ej. un plugin)
  --limite N, --max-dolares N, --rehacer, --simular   (como en voces_fnv.py)
"""

import concurrent.futures
import difflib
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA))

try:
    import wildcard_nl as wc
except ImportError:
    sys.exit("Falta wildcard_nl.py en esta carpeta.")
try:
    import voces_fnv_vertex as vx          # al importarlo, conecta voces_fnv.py con Vertex
    base = vx.base
except ImportError as e:
    sys.exit(f"Faltan voces_fnv.py / voces_fnv_vertex.py en esta carpeta ({e}).")

ErrorFatal = base.ErrorFatal
MOD_VOCES = "[NL] Stemmen"
MOD_SALIDA = "[NL] Wild Card Stemmen"
EXCLUIR = {MOD_VOCES.lower(), MOD_SALIDA.lower(), wc.MOD_NL.lower()}
OFICIALES = {o.lower() for o in wc.OFICIALES}
EMOCIONES = ["neutral", "anger", "disgust", "fear", "sad", "happy", "surprise", "pain"]
EXT_AUDIO = (".ogg", ".wav", ".mp3")
CSV_LISTA = CARPETA / "voces_wildcard_lista.csv"
CSV_PROBLEMAS = CARPETA / "voces_wildcard_problemas.csv"

NOMBRES_CATEGORIA = {
    "cambiada": "A) Juego base/DLC, frase cambiada por un mod -> regenerar",
    "oficial_ok": "A) Juego base/DLC, ya doblada (sin cambios)",
    "oficial_sin_doblar": "B) Juego base/DLC, sin voz holandesa todavía",
    "mod": "C) Diálogos de mods con audio inglés -> doblar",
}


# ---------------------------------------------------------------- plugins

def recorrer_registros(buf, tipos):
    """(tipo, formid, datos) de los registros de esos tipos (descomprimidos)."""
    salida = []

    def recorrer(p, fin):
        while p + wc.CABECERA <= fin:
            sig = bytes(buf[p:p + 4])
            tam = struct.unpack_from("<I", buf, p + 4)[0]
            if sig == b"GRUP":
                recorrer(p + wc.CABECERA, p + tam)
                p += tam
                continue
            flags, formid = struct.unpack_from("<II", buf, p + 8)
            if sig in tipos:
                cuerpo = bytes(buf[p + wc.CABECERA:p + wc.CABECERA + tam])
                try:
                    datos = wc.descomprimir(cuerpo) if flags & wc.COMPRIMIDO else cuerpo
                    salida.append((sig, formid, datos))
                except Exception:
                    pass
            p += wc.CABECERA + tam

    tam_tes4 = struct.unpack_from("<I", buf, 4)[0]
    recorrer(wc.CABECERA + tam_tes4, len(buf))
    return salida


def maestros_de(buf):
    tam = struct.unpack_from("<I", buf, 4)[0]
    return [wc.como_texto(d) or "" for s, d in wc.subregistros(bytes(buf[wc.CABECERA:wc.CABECERA + tam]))
            if s == b"MAST"]


def respuestas_de(datos):
    """{número: {emocion, intensidad, en, notas}} de un INFO."""
    resps, actual = {}, None
    for sig, d in wc.subregistros(datos):
        if sig == b"TRDT" and len(d) >= 13:
            emo, valor = struct.unpack_from("<Ii", d, 0)
            actual = {"emocion": EMOCIONES[emo] if emo < len(EMOCIONES) else "neutral",
                      "intensidad": str(valor), "en": "", "notas": ""}
            resps[d[12]] = actual
        elif actual is not None and sig == b"NAM1":
            actual["en"] = wc.normalizar(wc.como_texto(d) or "")
        elif actual is not None and sig == b"NAM2":
            actual["notas"] = wc.normalizar(wc.como_texto(d) or "")
    return resps


def leer_dialogos(ml):
    """INFO ganadores: {(plugin de origen, formid de 24 bits 'xxxxxxxx'): respuestas}, y géneros VTYP."""
    infos, generos = {}, {}
    for i, plugin in enumerate(ml.plugins, 1):
        ruta, _ = ml.buscar(plugin)
        if ruta is None:
            continue
        print(f"\r  Leyendo diálogos {i}/{len(ml.plugins)}: {plugin[:50]:<50}", end="", flush=True)
        buf = memoryview(ruta.read_bytes())
        if bytes(buf[:4]) != b"TES4":
            continue
        maestros = [m.lower() for m in maestros_de(buf)]
        propio = plugin.lower()
        for sig, formid, datos in recorrer_registros(buf, {b"INFO", b"VTYP"}):
            if sig == b"VTYP":
                edid, femenino = "", False
                for s, d in wc.subregistros(datos):
                    if s == b"EDID":
                        edid = (wc.como_texto(d) or "").lower()
                    elif s == b"DNAM" and d:
                        femenino = bool(d[0] & 2)
                if edid:
                    generos[edid] = "F" if femenino else "M"
                continue
            idx = formid >> 24
            origen = maestros[idx] if idx < len(maestros) else propio
            infos[(origen, f"{formid & 0xFFFFFF:08x}")] = respuestas_de(datos)
    print("\r" + " " * 90 + "\r", end="")
    return infos, generos


# ---------------------------------------------------------------- audios del modlist

def audios_sueltos(carpeta):
    """{ruta relativa en minúsculas: Path} de sound\\voice dentro de una carpeta."""
    salida = {}
    raiz = carpeta / "sound" / "voice"
    if not raiz.is_dir():
        return salida
    for dirpath, _, archivos in os.walk(raiz):
        for a in archivos:
            if a.lower().endswith(EXT_AUDIO):
                p = Path(dirpath) / a
                salida[str(p.relative_to(carpeta)).replace("/", "\\").lower()] = p
    return salida


def bsas_de(carpeta):
    if not carpeta.is_dir():
        return []
    return sorted(f for f in carpeta.iterdir() if f.is_file() and f.suffix.lower() == ".bsa")


def leer_audios(ml):
    """{ruta interna: (origen, fuente)} del modlist; origen = nombre de mod o 'juego'.
    fuente = Path (archivo suelto) o (ArchivoBSA, ruta interna)."""
    carpetas = [(ml.overwrite, "overwrite")] + [(ml.mods / m, m) for m in ml.mods_activos] + [(ml.data, "juego")]
    audios = {}
    for carpeta, nombre in carpetas:                 # primero los sueltos (ganan a los BSA)
        for ruta, p in audios_sueltos(carpeta).items():
            audios.setdefault(ruta, (nombre, p))
    for carpeta, nombre in carpetas:
        for f in bsas_de(carpeta):
            try:
                bsa = base.ArchivoBSA(f)
            except ErrorFatal:
                continue
            for ruta in bsa.archivos:
                if ruta.startswith("sound\\voice\\") and ruta.endswith(EXT_AUDIO):
                    audios.setdefault(ruta, (nombre, (bsa, ruta)))
    return audios


def leer_bytes(fuente):
    if isinstance(fuente, Path):
        return fuente.read_bytes()
    bsa, ruta = fuente
    return bsa.extraer(ruta)


# ---------------------------------------------------------------- textos

def cargar_traducciones(carpeta):
    ruta = carpeta / "traducciones_nl.txt"
    if not ruta.exists():
        raise ErrorFatal(f"No encuentro {ruta}. Haz antes los pasos de texto (exportar-xedit y copiar a WILDCARD).")
    pares = {}
    for linea in wc.leer_texto(ruta).splitlines():
        p = linea.find("\t")
        if p > 0:
            pares.setdefault(wc.clave(linea[:p]), base.desescapar(linea[p + 1:]))
    return pares


def cargar_voces_antiguas(es):
    """Textos con los que se generaron tus voces holandesas: {(plugin, formid, n): {nl, en}}."""
    salida, leidos = {}, []
    candidatos = [("falloutnv.esm", es / "voces_nl.txt")]
    for f in sorted(es.glob("voces_nl_*.txt")):
        candidatos.append((f.stem[len("voces_nl_"):].lower() + ".esm", f))
    for plugin, ruta in candidatos:
        if not ruta.exists():
            continue
        try:
            lineas, _ = base.leer_voces(ruta)
        except ErrorFatal:
            continue
        for (formid, n), d in lineas.items():
            salida[(plugin, formid, n)] = d
        leidos.append(ruta.name)
    return salida, leidos


def ruta_es(opciones):
    if opciones.get("es"):
        return Path(opciones["es"])
    return CARPETA.parent / "FNVEdit 4.1.5f" / "Edit Scripts"


def iguales(a, b):
    return wc.clave(base.texto_para_voz(a or "")) == wc.clave(base.texto_para_voz(b or ""))


# ---------------------------------------------------------------- análisis

def analizar(ml, opciones):
    carpeta = Path(opciones.get("carpeta") or CARPETA / "WILDCARD")
    trad = cargar_traducciones(carpeta)
    es = ruta_es(opciones)
    antiguas, leidos = cargar_voces_antiguas(es)
    print(f"\nPerfil: {ml.perfil}")
    print(f"Traducciones: {len(trad):,} ({carpeta.name})")
    print(f"Textos de tus voces holandesas: {', '.join(leidos) if leidos else 'NO ENCONTRADOS en ' + str(es)}")
    if not leidos:
        print("   (sin ellos no puedo saber qué frases del juego base cambió un mod; usa --es)")

    ml.mods_activos = [m for m in ml.mods_activos if m.lower() not in EXCLUIR]
    infos, generos = leer_dialogos(ml)
    print(f"Diálogos (INFO) en el orden de carga: {len(infos):,}")
    print("Leyendo la lista de audios del modlist (BSA y sueltos)...")
    audios = leer_audios(ml)
    holandeses = set(audios_sueltos(ml.mods / MOD_VOCES))
    print(f"Audios de diálogo encontrados: {len(audios):,}   ya en {MOD_VOCES}: {len(holandeses):,}")

    lineas, contadores, usados = [], {}, set()
    filtros = [f.lower() for f in opciones.get("filtro") or []]

    def contar(c):
        contadores[c] = contadores.get(c, 0) + 1

    for ruta, (origen_mod, fuente) in audios.items():
        partes = ruta.split("\\")
        if len(partes) < 5:
            continue
        m = base.PATRON_VOZ.search(partes[-1])
        if not m:
            continue
        plugin, tipo = partes[2], partes[-2]
        formid, n = m.group(1).lower(), int(m.group(2))
        resps = infos.get((plugin, formid))
        if resps is not None:
            usados.add((plugin, formid))
        resp = (resps or {}).get(n)
        if resp is None or not resp["en"].strip():
            contar("sin_dialogo")
            continue
        nl = trad.get(wc.clave(resp["en"]))
        texto = base.texto_para_voz(nl or "")
        if not nl or not texto:
            contar("sin_traduccion")
            continue
        if texto == base.texto_para_voz(resp["en"]):
            contar("igual_ingles")
            continue
        if plugin in OFICIALES:
            if ruta in holandeses:
                vieja = antiguas.get((plugin, formid, n))
                if vieja and not iguales(vieja["en"], resp["en"]) and not iguales(vieja["nl"], nl):
                    cat = "cambiada"
                else:
                    cat = "oficial_ok"
            else:
                cat = "oficial_sin_doblar"
        else:
            cat = "mod"
        contar(cat)
        if filtros and not any(f in ruta for f in filtros):
            continue
        parecido = None
        if cat == "cambiada":
            vieja = antiguas[(plugin, formid, n)]
            parecido = difflib.SequenceMatcher(None, vieja["en"], resp["en"]).ratio()
        lineas.append({"cat": cat, "ruta": ruta, "fuente": fuente, "origen": origen_mod, "plugin": plugin,
                       "tipo": tipo, "texto": texto, "en": resp["en"], "nl": nl, "parecido": parecido,
                       "linea": {"emocion": resp["emocion"], "intensidad": resp["intensidad"],
                                 "notas": resp["notas"], "en": resp["en"], "nl": nl, "mision": ""}})

    sin_audio = 0
    for (plugin, formid), resps in infos.items():
        if plugin in OFICIALES or (plugin, formid) in usados:
            continue
        sin_audio += sum(1 for r in resps.values() if r["en"].strip())
    contadores["mod_sin_audio"] = sin_audio
    return lineas, contadores, generos


# ---------------------------------------------------------------- coste

def resumen_coste(lineas, cfg, tipos_cfg):
    unicos, por_cat = {}, {}
    for l in lineas:
        modelo = base.modelo_de(l["tipo"], tipos_cfg.get(l["tipo"]), cfg)
        k = (modelo, l["tipo"], l["texto"])
        if k not in unicos:
            unicos[k] = l["cat"]
    for (modelo, tipo, texto), cat in unicos.items():
        s = base.segundos_estimados(texto)
        d = por_cat.setdefault(cat, [0, 0.0, 0.0])
        d[0] += 1
        d[1] += s
        d[2] += base.coste(s, cfg, modelo)
    return por_cat


def comando_contar(ml, opciones, cfg):
    lineas, cont, generos = analizar(ml, opciones)
    tipos_cfg = base.leer_json(base.ARCHIVO_TIPOS, {}).get("tipos", {})

    # Tipos de voz nuevos (de mods) -> voces_tipos.json, sin tocar los que ya tienes
    nuevos_est, ejemplos = {}, {}
    for l in lineas:
        if l["tipo"] not in tipos_cfg and l["cat"] in ("mod", "oficial_sin_doblar"):
            e = nuevos_est.setdefault(l["tipo"], [0, 0])
            e[0] += 1
            e[1] += len(l["texto"])
            ejemplos.setdefault(l["tipo"], l["texto"])
    if nuevos_est:
        generos_todos = {**generos}
        nuevos, _, tipos_cfg = base.actualizar_tipos(nuevos_est, generos_todos, ejemplos, cfg)
        print(f"\nTipos de voz nuevos añadidos a voces_tipos.json: {nuevos}")

    print("\n" + "=" * 78)
    print(f"{'Categoría':<62}{'audios':>10}")
    print("-" * 78)
    for c in ("cambiada", "oficial_ok", "oficial_sin_doblar", "mod"):
        print(f"{NOMBRES_CATEGORIA[c]:<62}{cont.get(c, 0):>10,}")
    print(f"{'D) Diálogos de mods SIN audio (quedan con subtítulo)':<62}{cont.get('mod_sin_audio', 0):>10,}")
    print(f"{'Sin traducción holandesa / igual que en inglés (se saltan)':<62}"
          f"{cont.get('sin_traduccion', 0) + cont.get('igual_ingles', 0):>10,}")
    print(f"{'Audios sin diálogo que les corresponda (se saltan)':<62}{cont.get('sin_dialogo', 0):>10,}")
    print("=" * 78)

    cambiadas = [l for l in lineas if l["cat"] == "cambiada"]
    if cambiadas:
        leves = sum(1 for l in cambiadas if l["parecido"] >= 0.9)
        print(f"\nFrases cambiadas: {len(cambiadas):,}  (erratas o retoques mínimos: {leves:,}; "
              f"cambios más grandes: {len(cambiadas) - leves:,})")
        for l in sorted(cambiadas, key=lambda x: x["parecido"])[:5]:
            print(f"   {l['parecido']:.0%} parecido  EN: {l['en'][:80]!r}")

    mods = {}
    for l in lineas:
        if l["cat"] == "mod":
            d = mods.setdefault(l["plugin"], [0, set()])
            d[0] += 1
            d[1].add(l["tipo"])
    if mods:
        print("\nDiálogos con audio por plugin de mod:")
        for p, (n, ts) in sorted(mods.items(), key=lambda x: -x[1][0])[:25]:
            print(f"   {n:>6,}  {p}  ({len(ts)} tipos de voz)")

    print("\nCoste estimado (audios distintos; +10-20 % por reintentos; x2 desde 2027):")
    total = 0.0
    for c, (n, s, usd) in sorted(resumen_coste([l for l in lineas if l["cat"] != "oficial_ok"], cfg,
                                               tipos_cfg).items()):
        print(f"   {NOMBRES_CATEGORIA[c][:48]:<48} {n:>7,} audios {s / 3600:>6.1f} h {usd:>8.2f} USD")
        if c != "oficial_sin_doblar":
            total += usd
    print(f"   {'Total por defecto (A cambiadas + C mods)':<48} {'':>14} {'':>8} {total:>8.2f} USD")
    print("   (B solo se genera con --incluir-oficiales)")

    filas = [(l["cat"], l["plugin"], l["tipo"], l["ruta"], l["origen"], l["en"], l["nl"],
              "" if l["parecido"] is None else f"{l['parecido']:.2f}")
             for l in lineas if l["cat"] != "oficial_ok"]
    ruta = base.escribir_csv(CSV_LISTA, ["categoria", "plugin", "tipo", "archivo", "mod", "ingles",
                                         "holandes", "parecido"], filas)
    print(f"\nLista completa (para revisar en Excel): {ruta.name}")
    print("Revisa en voces_tipos.json la voz/efecto de los tipos nuevos antes de 'generar'.")
    print("Siguiente: python voces_wildcard.py generar --limite 20 --max-dolares 1\n")


# ---------------------------------------------------------------- generación

def formato_de(lineas_plugin):
    """Frecuencia y canales de los audios originales de un plugin."""
    if not shutil.which("ffprobe"):
        return 44100, 1
    for l in lineas_plugin[:5]:
        try:
            datos = leer_bytes(l["fuente"])
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                                "stream=sample_rate,channels", "-of", "json", "-"],
                               input=datos, capture_output=True, timeout=30)
            s = json.loads(r.stdout)["streams"][0]
            return int(s["sample_rate"]), int(s["channels"])
        except Exception:
            continue
    return 44100, 1


def convertir(wav, destino, efecto, hz_salida, canales, cfg):
    hz = base.duracion_wav(wav.read_bytes())[1]
    filtro = base.EFECTOS.get(efecto or "", "").format(hz=hz, hz_082=int(hz * 0.82), hz_094=int(hz * 0.94))
    cadena = ",".join(x for x in (filtro, f"loudnorm=I={cfg['tts_volumen_lufs']}:TP=-2:LRA=11",
                                  f"aresample={hz_salida}") if x)
    destino.parent.mkdir(parents=True, exist_ok=True)
    es_wav = destino.suffix.lower() == ".wav"
    tmp = destino.with_name(destino.stem + ".tmp" + destino.suffix)
    codec = ["-c:a", "pcm_s16le"] if es_wav else ["-c:a", "libvorbis", "-q:a", "5"]
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af", cadena,
                        "-ac", str(canales)] + codec + [str(tmp)], capture_output=True, text=True)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        return r.stderr.strip()[-300:] or "error de ffmpeg"
    tmp.replace(destino)
    return None


def comando_generar(ml, opciones, cfg):
    base.comprobar_ffmpeg()
    simular = opciones.get("simular")
    tipos_cfg = base.leer_json(base.ARCHIVO_TIPOS, {}).get("tipos", {})
    if not tipos_cfg:
        raise ErrorFatal("No existe voces_tipos.json. Ejecuta primero 'contar'.")
    lineas, _, _ = analizar(ml, opciones)
    cats = {"cambiada", "mod"}
    if opciones.get("incluir_oficiales"):
        cats.add("oficial_sin_doblar")
    solo = opciones.get("solo")
    if solo == "mods":
        cats = {"mod"}
    elif solo == "cambiadas":
        cats = {"cambiada"}
    lineas = [l for l in lineas if l["cat"] in cats]
    if not lineas:
        print("\nNo hay nada que generar con estas opciones.\n")
        return

    sufijo = "_SIMULADO" if simular else ""
    cache = CARPETA / f"cache_voces{sufijo}"
    salida = (CARPETA / f"salida_voces_wildcard{sufijo}") if simular else ml.mods / MOD_SALIDA

    def clave_de(modelo, voz, estilo, texto):
        return hashlib.sha1(f"{modelo}|{voz}|{estilo}|{texto}".encode()).hexdigest()[:24]

    def ruta_cache(clave):
        return cache / clave[:2] / f"{clave}.wav"

    por_plugin = {}
    for l in lineas:
        por_plugin.setdefault(l["plugin"], []).append(l)
    formatos = {p: formato_de(ls) for p, ls in por_plugin.items()}

    trabajos, sin_voz, mp3 = {}, set(), 0
    for l in lineas:
        t = tipos_cfg.get(l["tipo"])
        if not t or not t.get("voz"):
            sin_voz.add(l["tipo"])
            continue
        ext = Path(l["ruta"]).suffix.lower()
        if ext == ".mp3":
            mp3 += 1
            continue
        estilo = base.estilo_de(l["linea"], t)
        modelo = base.modelo_de(l["tipo"], t, cfg)
        clave = clave_de(modelo, t["voz"], estilo, l["texto"])
        alternativa = clave_de(base.FLASH, t["voz"], estilo, l["texto"]) if modelo != base.FLASH else None
        destino = salida / Path(*l["ruta"].split("\\"))
        j = trabajos.setdefault(clave, {"texto": l["texto"], "voz": t["voz"], "estilo": estilo, "modelo": modelo,
                                        "alternativa": alternativa, "destinos": [], "en": l["en"], "tipo": l["tipo"]})
        hz, can = formatos[l["plugin"]]
        j["destinos"].append((destino, t.get("efecto", ""), hz, can))
    if sin_voz:
        print(f"Sin voz asignada en voces_tipos.json (se saltan; ejecuta 'contar'): {', '.join(sorted(sin_voz))}")
    if mp3:
        print(f"Audios .mp3 (no se tocan): {mp3}")

    def wav_de(clave):
        propio = ruta_cache(clave)
        alt = trabajos[clave]["alternativa"]
        if not propio.exists() and alt and ruta_cache(alt).exists():
            return ruta_cache(alt)
        return propio

    pendientes = [c for c in trabajos if not wav_de(c).exists()]
    limite = int(opciones.get("limite") or 0)
    if limite:
        pendientes = pendientes[:limite]
    max_dolares = float(opciones.get("max_dolares") or 5)
    estimado = sum(base.coste(base.segundos_estimados(trabajos[c]["texto"]), cfg, trabajos[c]["modelo"])
                   for c in pendientes)
    print(f"\nAudios distintos: {len(trabajos):,} (en caché: {len(trabajos) - len(pendientes):,}, "
          f"por generar: {len(pendientes):,}, ~{estimado:.2f} USD). Tope: {max_dolares:.2f} USD")
    print(f"Salida: {salida}\n")

    uso = base.leer_json(base.ARCHIVO_USO, {})
    uso.setdefault("gemini_tts_segundos", {})
    uso.setdefault("gemini_tts_usd", {})
    funcion = base.tts_simulado if simular else base.tts_gemini
    limitadores = {}
    for c in pendientes:
        limitadores.setdefault(trabajos[c]["modelo"], base.Limitador(cfg["tts_rpm"]))
    problemas, errores = [], []
    gastado, generados = 0.0, 0
    convertidos = [0]
    lock = threading.Lock()
    rehacer = opciones.get("rehacer")

    def convertir_trabajo(clave):
        j = trabajos[clave]
        for destino, efecto, hz, can in j["destinos"]:
            if destino.exists() and not rehacer:
                continue
            error = convertir(wav_de(clave), destino, efecto, hz, can, cfg)
            with lock:
                if error:
                    errores.append((str(destino), error))
                else:
                    convertidos[0] += 1

    hilos = max(1, int(cfg["tts_hilos"]))
    conversor = concurrent.futures.ThreadPoolExecutor(max_workers=hilos)
    conversiones = [conversor.submit(convertir_trabajo, c) for c in trabajos if wav_de(c).exists()]
    detenido = None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=hilos) as pool:
            cola = list(pendientes)
            while cola:
                if gastado >= max_dolares:
                    detenido = f"Tope de gasto alcanzado ({gastado:.2f} USD). Sube --max-dolares para continuar."
                    break
                bloque, cola = cola[:hilos * 5], cola[hilos * 5:]
                futuros = {pool.submit(funcion, trabajos[c]["texto"], trabajos[c]["voz"], trabajos[c]["estilo"],
                                       cfg, limitadores[trabajos[c]["modelo"]], trabajos[c]["modelo"]): c
                           for c in bloque}
                for fut in concurrent.futures.as_completed(futuros):
                    clave = futuros[fut]
                    j = trabajos[clave]
                    wav, problema = fut.result()
                    if wav is not None:
                        segundos = base.duracion_wav(wav)[0]
                        c_audio = base.coste(segundos, cfg, j["modelo"])
                        gastado += c_audio
                        hoy = base.hoy()
                        uso["gemini_tts_segundos"][hoy] = uso["gemini_tts_segundos"].get(hoy, 0) + segundos
                        uso["gemini_tts_usd"][hoy] = uso["gemini_tts_usd"].get(hoy, 0) + c_audio
                        problema = base.motivo_audio(j["texto"], segundos)
                        if problema:
                            dudoso = cache / "_dudosos" / f"{clave}.wav"
                            dudoso.parent.mkdir(parents=True, exist_ok=True)
                            dudoso.write_bytes(wav)
                        else:
                            destino = ruta_cache(clave)
                            destino.parent.mkdir(parents=True, exist_ok=True)
                            destino.write_bytes(wav)
                            generados += 1
                            conversiones.append(conversor.submit(convertir_trabajo, clave))
                    if problema:
                        problemas.append((j["tipo"], j["voz"], j["modelo"], problema, j["texto"], j["en"],
                                          str(j["destinos"][0][0])))
                if not simular:
                    base.guardar_json(base.ARCHIVO_USO, uso)
                print(f"   {generados:,} audios nuevos · {gastado:.2f} USD")
    except KeyboardInterrupt:
        detenido = "Interrumpido con Ctrl+C. Lo generado está guardado; vuelve a ejecutar para continuar."
    except ErrorFatal as e:
        detenido = f"{e}\nLo generado hasta ahora está guardado; al volver a ejecutar, continúa."

    print("\nConvirtiendo audios...")
    for c in conversiones:
        c.result()
    conversor.shutdown()
    if problemas:
        base.escribir_csv(CSV_PROBLEMAS, ["tipo", "voz", "modelo", "motivo", "holandes", "ingles", "archivo"],
                          problemas)
    print("\n" + "=" * 64)
    print(f"Audios generados en esta ejecución: {generados:,}  ({gastado:.2f} USD aprox.)")
    print(f"Archivos escritos:                  {convertidos[0]:,}")
    print(f"Mod de MO2:                         {salida}")
    if problemas:
        print(f"Con problemas (se reintentan):      {len(problemas)} -> {CSV_PROBLEMAS.name}")
    if errores:
        print(f"Errores de ffmpeg:                  {len(errores)} (primero: {errores[0][1]})")
    if detenido:
        print("\n" + detenido)
    print("=" * 64)
    if not simular:
        print(f'En MO2: F5, activa "{MOD_SALIDA}" y ponlo DEBAJO de "{MOD_VOCES}".\n')


# ---------------------------------------------------------------- main

def main():
    args = sys.argv[1:]
    opciones = {}
    for nombre in ("mo2", "perfil", "carpeta", "es", "solo", "limite", "max-dolares"):
        bandera = "--" + nombre
        if bandera in args:
            i = args.index(bandera)
            if i + 1 >= len(args):
                raise ErrorFatal(f"Falta el valor de {bandera}")
            opciones[nombre.replace("-", "_")] = args[i + 1]
            del args[i:i + 2]
    for bandera in ("incluir-oficiales", "rehacer", "simular"):
        if "--" + bandera in args:
            opciones[bandera.replace("-", "_")] = True
            args.remove("--" + bandera)
    if "--filtro" in args:
        i = args.index("--filtro")
        valores = []
        for v in args[i + 1:]:
            if v.startswith("--"):
                break
            valores.append(v)
        opciones["filtro"] = valores
        del args[i:i + 1 + len(valores)]
    if opciones.get("solo") not in (None, "mods", "cambiadas"):
        raise ErrorFatal("--solo debe ser 'mods' o 'cambiadas'.")
    if not args or args[0] not in ("contar", "generar"):
        print(__doc__)
        return

    cfg = base.leer_config()
    vx.FORMATO_TONO[0] = bool(cfg.get("tts_formato_tono", False))
    vx.VERIFICAR[0] = bool(cfg.get("tts_verificar", True))
    if cfg.get("tts_notas_ingles", False):
        base.estilo_de = vx.estilo_con_notas(base.estilo_de)
    ml = wc.Modlist(opciones.get("mo2") or wc.MO2_POR_DEFECTO, opciones.get("perfil"))
    if args[0] == "contar":
        comando_contar(ml, opciones, cfg)
    else:
        comando_generar(ml, opciones, cfg)


if __name__ == "__main__":
    try:
        main()
    except (ErrorFatal, wc.ErrorFatal) as e:
        sys.exit(f"\nError: {e}")
