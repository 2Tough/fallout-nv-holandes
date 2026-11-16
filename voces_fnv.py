#!/usr/bin/env python3
"""
voces_fnv.py
Genera las voces en holandés de Fallout: New Vegas con Gemini TTS, a partir del texto ya
traducido en FalloutNV_NL.esp.

Pasos:
  1. FNVEdit (FalloutNV.esm + FalloutNV_NL.esp) -> Apply Script -> Exportar_Voces
     (crea voces_nl.txt y voces_tipos.txt en "Edit Scripts").
  2. python voces_fnv.py catalogo                     -> voces holandesas disponibles en Gemini
  3. python voces_fnv.py contar  BSA VOCES [--filtro]  -> cuántas líneas, cuánto audio, cuánto cuesta,
                                                        y crea voces_tipos.json (qué voz y qué modelo
                                                        usa cada tipo)
  4. python voces_fnv.py muestras                     -> una frase de prueba con cada voz (céntimos)
  5. python voces_fnv.py generar BSA VOCES --filtro vcg01 vcg02 --max-dolares 1   -> prueba pequeña
  6. python voces_fnv.py generar BSA VOCES --max-dolares 80                       -> todo el juego

  BSA   = "...\\Fallout New Vegas\\Data\\Fallout - Voices1.bsa"
  VOCES = "...\\Edit Scripts\\voces_nl.txt"

  Otros:
  python voces_fnv.py probar "Hé, vreemdeling." --voz Algenib --estilo "tired" --efecto necrofago
         [--modelo gemini-3.8-flash-lite-tts]

Modelos: cada tipo de voz tiene un campo 'modelo' en voces_tipos.json. Por defecto, los personajes
principales (tipos con "unique" en el nombre o en 'tts_principales' de config.json) usan
'tts_modelo' (Flash) y el resto de NPC usan 'tts_modelo_npc' (Flash-Lite, más barato).

Caché: cada audio generado se guarda en cache_voces\\ (un .wav por combinación de modelo, voz,
estilo y texto). Nunca se paga dos veces por el mismo audio: si cambias el efecto o vuelves a
convertir, se reutiliza; si cambias la voz o el estilo de un tipo, solo se regenera ese tipo.
Si un NPC pasa a Flash-Lite y ya tenía audio hecho con Flash, se reutiliza el de Flash.
Los .ogg finales van a salida_voces\\Sound\\Voice\\FalloutNV.esm\\<tipo de voz>\\.

Necesita: Python 3.10+, requests (ya instalado) y ffmpeg (winget install Gyan.FFmpeg).
"""

import argparse
import base64
import concurrent.futures
import csv
import datetime
import hashlib
import io
import json
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import wave
import zlib
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
ARCHIVO_CONFIG = CARPETA / "config.json"
ARCHIVO_USO = CARPETA / "uso.json"
ARCHIVO_TIPOS = CARPETA / "voces_tipos.json"
ARCHIVO_CATALOGO = CARPETA / "voces_catalogo.json"
CARPETA_CACHE = CARPETA / "cache_voces"
CARPETA_SALIDA = CARPETA / "salida_voces"
CARPETA_MUESTRAS = CARPETA / "muestras_voces"

API = "https://generativelanguage.googleapis.com/v1beta"

FLASH = "gemini-3.8-flash-tts"
FLASH_LITE = "gemini-3.8-flash-lite-tts"

CONFIG_DEFECTO = {
    "gemini_clave": "",
    "tts_modelo": FLASH,                        # modelo de los personajes principales
    "tts_modelo_npc": FLASH_LITE,               # modelo del resto de NPC (más barato)
    "tts_principales": [],                      # tipos de voz extra que deben usar 'tts_modelo'
    "tts_precios": {FLASH: 9.0, FLASH_LITE: 6.0},  # USD por millón de tokens de audio (x2 desde 2027)
    "tts_hilos": 4,                             # peticiones en paralelo
    "tts_rpm": 60,                              # máximo de peticiones por minuto (por modelo)
    "tts_idiomas": ["nl-NL"],                   # idiomas del catálogo de voces
    "tts_volumen_lufs": -18,                    # volumen final (más negativo = más bajo)
}

TOKENS_POR_SEGUNDO = 25          # tokens de audio de Gemini por segundo de audio
CARACTERES_POR_SEGUNDO = 14      # velocidad aproximada del habla en holandés (para estimar)

FRASE_MUESTRA = ("Hé, vreemdeling. Welkom in Goodsprings. Als je problemen zoekt, "
                 "ben je hier aan het verkeerde adres... maar een drankje kan altijd.")

# Voces "prebuilt" (multilingües) por si el catálogo holandés no está disponible.
VOCES_BASE = {
    "Zephyr": "F", "Kore": "F", "Leda": "F", "Aoede": "F", "Callirrhoe": "F", "Autonoe": "F",
    "Despina": "F", "Erinome": "F", "Laomedeia": "F", "Achernar": "F", "Gacrux": "F",
    "Pulcherrima": "F", "Vindemiatrix": "F", "Sulafat": "F",
    "Puck": "M", "Charon": "M", "Fenrir": "M", "Orus": "M", "Enceladus": "M", "Iapetus": "M",
    "Umbriel": "M", "Algieba": "M", "Algenib": "M", "Rasalgethi": "M", "Alnilam": "M",
    "Schedar": "M", "Achird": "M", "Zubenelgenubi": "M", "Sadachbia": "M", "Sadaltager": "M",
}

# Emoción del juego (TRDT) -> instrucción de estilo para la voz
EMOCIONES = {
    "anger": "angry", "disgust": "disgusted", "fear": "scared", "sad": "sad",
    "happy": "happy", "surprise": "surprised", "pain": "in pain",
}

# Efectos de ffmpeg por tipo de personaje. {hz} = frecuencia del audio de Gemini.
EFECTOS = {
    "": "",
    "robot": "afftfilt=real='hypot(re,im)*sin(0)':imag='hypot(re,im)*cos(0)':win_size=512:overlap=0.75,"
             "highpass=f=200",
    "robot_suave": "aecho=0.8:0.85:12|24:0.35|0.2,highpass=f=250,lowpass=f=6500",
    "mutante": "asetrate={hz_082},aresample={hz},atempo=1.2195,lowpass=f=6000",
    "necrofago": "asetrate={hz_094},aresample={hz},atempo=1.0638,"
                 "acrusher=bits=10:mix=0.15:mode=log,highpass=f=120",
    "radio": "highpass=f=400,lowpass=f=3500,acrusher=bits=12:mix=0.1",
}

# Pistas en el nombre del tipo de voz -> efecto propuesto (se puede cambiar en voces_tipos.json)
PISTAS_EFECTO = [
    (("protectron", "eyebot", "mrhandy", "misterhandy", "mistergutsy", "robobrain", "sentrybot",
      "robot"), "robot"),
    (("securitron", "yesman", "victor"), "robot_suave"),
    (("supermutant", "nightkin", "mutant"), "mutante"),
    (("ghoul",), "necrofago"),
]


class ErrorFatal(Exception):
    pass


class LimiteDiario(ErrorFatal):
    """Un modelo llegó a su límite de peticiones del día (los demás modelos pueden seguir)."""
    def __init__(self, modelo):
        super().__init__(f"Se alcanzó el límite DIARIO de Gemini TTS ({modelo}).")
        self.modelo = modelo


# ---------------------------------------------------------------- archivos

def leer_json(ruta, defecto):
    if ruta.exists():
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    return defecto


def guardar_json(ruta, datos):
    tmp = ruta.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    tmp.replace(ruta)


def leer_texto(ruta):
    datos = ruta.read_bytes()
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return datos.decode("cp1252")


def escribir_csv(ruta, cabecera, filas):
    for intento in range(2):
        try:
            with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(cabecera)
                w.writerows(filas)
            return ruta
        except PermissionError:
            if intento:
                raise
            ruta = ruta.with_name(f"{ruta.stem}_{datetime.datetime.now():%H%M%S}{ruta.suffix}")
    return ruta


def leer_config():
    usuario = leer_json(ARCHIVO_CONFIG, {})
    cfg = {**CONFIG_DEFECTO, **usuario}
    for k, v in CONFIG_DEFECTO.items():
        if cfg.get(k) in (None, ""):
            cfg[k] = v
    cfg["tts_precios"] = {**CONFIG_DEFECTO["tts_precios"], **(usuario.get("tts_precios") or {})}
    # Compatibilidad: el antiguo 'tts_precio_audio_millon' es el precio de 'tts_modelo'
    if usuario.get("tts_precio_audio_millon") and not (usuario.get("tts_precios") or {}).get(cfg["tts_modelo"]):
        cfg["tts_precios"][cfg["tts_modelo"]] = float(usuario["tts_precio_audio_millon"])
    cfg["tts_principales"] = [t.lower() for t in cfg.get("tts_principales") or []]
    return cfg


def tiene_clave(cfg):
    clave = (cfg.get("gemini_clave") or "").strip()
    return bool(clave) and "PEGA_AQUI" not in clave


def hoy():
    return datetime.date.today().isoformat()


# ---------------------------------------------------------------- BSA de Fallout 3 / New Vegas (versión 104)

class ArchivoBSA:
    """Lee la lista de archivos de un .bsa de Fallout 3 / New Vegas y extrae archivos sueltos."""

    def __init__(self, ruta):
        self.ruta = Path(ruta)
        if not self.ruta.exists():
            raise ErrorFatal(f"No encuentro {self.ruta}")
        with open(self.ruta, "rb") as f:
            cab = f.read(36)
            if len(cab) < 36 or cab[:4] != b"BSA\x00":
                raise ErrorFatal(f"{self.ruta.name} no es un archivo .bsa.")
            (version, inicio, self.flags, n_carpetas, n_archivos,
             _, lon_nombres, _) = struct.unpack("<8I", cab[4:36])
            if version != 104:
                raise ErrorFatal(f"{self.ruta.name}: versión {version} de BSA; se esperaba 104 (New Vegas).")
            f.seek(inicio)
            carpetas = [struct.unpack("<QII", f.read(16)) for _ in range(n_carpetas)]
            registros = []
            for _, cuenta, _ in carpetas:
                carpeta = ""
                if self.flags & 1:
                    n = f.read(1)[0]
                    carpeta = f.read(n).rstrip(b"\x00").decode("cp1252")
                for _ in range(cuenta):
                    _, tam, off = struct.unpack("<QII", f.read(16))
                    registros.append((carpeta, tam, off))
            nombres = []
            if self.flags & 2:
                nombres = [x.decode("cp1252") for x in f.read(lon_nombres).split(b"\x00")[:n_archivos]]
        if len(nombres) != len(registros):
            raise ErrorFatal(f"{self.ruta.name}: no pude leer los nombres de los archivos.")
        self.archivos = {}
        for (carpeta, tam, off), nombre in zip(registros, nombres):
            self.archivos[f"{carpeta}\\{nombre}".lower()] = (tam, off)

    def extraer(self, ruta_interna):
        tam, off = self.archivos[ruta_interna.lower()]
        comprimido = bool(self.flags & 4) != bool(tam & 0x40000000)
        tam &= 0x3FFFFFFF
        with open(self.ruta, "rb") as f:
            f.seek(off)
            datos = f.read(tam)
        if self.flags & 0x100 and datos and not datos.startswith((b"OggS", b"RIFF")):
            n = datos[0]                                   # nombre incrustado delante de los datos
            datos = datos[n + 1:]
        if comprimido:
            datos = zlib.decompress(datos[4:])
        return datos


PATRON_VOZ = re.compile(r"_([0-9a-f]{8})_(\d+)\.(ogg|wav|mp3)$", re.I)


def archivos_de_voz(bsa):
    """Devuelve [(ruta interna, tipo de voz, formid, número de respuesta)] de FalloutNV.esm."""
    salida, otros = [], 0
    for ruta in bsa.archivos:
        partes = ruta.split("\\")
        if len(partes) < 5 or partes[:3] != ["sound", "voice", "falloutnv.esm"]:
            continue
        m = PATRON_VOZ.search(partes[-1])
        if not m:
            otros += 1
            continue
        salida.append((ruta, partes[-2], m.group(1).lower(), int(m.group(2))))
    return salida, otros


# ---------------------------------------------------------------- textos exportados con Exportar_Voces.pas

def desescapar(s):
    return s.replace("{{NL}}", "\n").replace("{{TAB}}", "\t")


def leer_voces(ruta):
    ruta = Path(ruta)
    if not ruta.exists():
        raise ErrorFatal(f"No encuentro {ruta}. ¿Ejecutaste Exportar_Voces en FNVEdit?")
    lineas = {}
    for linea in leer_texto(ruta).splitlines():
        campos = linea.split("\t")
        if len(campos) < 7:
            continue
        formid, numero, emocion, intensidad, mision, notas, nl = campos[:7]
        en = campos[7] if len(campos) > 7 else ""
        try:
            clave = (formid.strip().lower().zfill(8), int(numero))
        except ValueError:
            continue
        lineas[clave] = {
            "emocion": emocion.strip(), "intensidad": intensidad.strip(), "mision": mision.strip(),
            "notas": desescapar(notas), "nl": desescapar(nl), "en": desescapar(en),
        }
    if not lineas:
        raise ErrorFatal(f"{ruta.name} está vacío o tiene otro formato.")
    generos = {}
    ruta_tipos = ruta.with_name("voces_tipos.txt")
    if ruta_tipos.exists():
        for linea in leer_texto(ruta_tipos).splitlines():
            if "\t" in linea:
                edid, g = linea.split("\t", 1)
                generos[edid.strip().lower()] = g.strip().upper()[:1]
    return lineas, generos


def texto_para_voz(texto):
    """Quita notas internas y etiquetas que no deben leerse en voz alta."""
    t = re.sub(r"<[^<>]*>|\{[^{}]*\}|\[[^\[\]]*\]|\*[^*\n]*\*|\*", " ", texto)
    t = re.sub(r"\s+", " ", t).strip()
    return t if re.search(r"[A-Za-zÀ-ÿ]", t) else ""


def estilo_de(linea, cfg_tipo):
    partes = []
    if cfg_tipo.get("estilo"):
        partes.append(cfg_tipo["estilo"].strip())
    emocion = linea["emocion"].lower()
    nombre = next((v for k, v in EMOCIONES.items() if emocion.startswith(k)), None)
    if nombre:
        try:
            valor = int(float(linea["intensidad"] or 0))
        except ValueError:
            valor = 0
        if valor >= 60:
            nombre = "very " + nombre
        elif 0 < valor < 25:
            nombre = "slightly " + nombre
        partes.append(nombre)
    notas = re.sub(r"[(){}\[\]]", "", linea["notas"]).strip()
    if notas and len(notas) <= 80 and "\n" not in notas:
        partes.append(notas)
    return ", ".join(partes)


# ---------------------------------------------------------------- tipos de voz -> voz holandesa y modelo

def voces_disponibles():
    """[(id, género, descripción)] del catálogo holandés, o las voces base si no hay catálogo."""
    catalogo = leer_json(ARCHIVO_CATALOGO, [])
    if catalogo:
        return [(v["id"], v.get("genero", "?"), v.get("descripcion", "")) for v in catalogo], True
    return [(n, g, "multilingüe") for n, g in VOCES_BASE.items()], False


def adivinar_genero(tipo, generos):
    if tipo in generos:
        return generos[tipo]
    if "female" in tipo or "woman" in tipo or "girl" in tipo:
        return "F"
    return "M"


def adivinar_efecto(tipo):
    for pistas, efecto in PISTAS_EFECTO:
        if any(p in tipo for p in pistas):
            return efecto
    return ""


def es_principal(tipo, cfg):
    return "unique" in tipo or tipo in cfg["tts_principales"]


def modelo_de(tipo, cfg_tipo, cfg):
    """Modelo de un tipo de voz: el de voces_tipos.json o, si no tiene, según sea principal o NPC."""
    return (cfg_tipo or {}).get("modelo") or (cfg["tts_modelo"] if es_principal(tipo, cfg)
                                              else cfg["tts_modelo_npc"])


def precio(modelo, cfg):
    return cfg["tts_precios"].get(modelo, cfg["tts_precios"].get(FLASH, 9.0))


def actualizar_tipos(estadisticas, generos, ejemplos, cfg):
    """Crea o completa voces_tipos.json sin tocar lo que ya editaste a mano."""
    datos = leer_json(ARCHIVO_TIPOS, {})
    tipos = datos.get("tipos", {})
    voces, del_catalogo = voces_disponibles()
    por_genero = {g: [v for v, gv, _ in voces if gv == g] for g in ("F", "M")}
    usados = {g: 0 for g in ("F", "M")}
    for t in tipos.values():
        g = t.get("genero", "M")
        if t.get("voz") in por_genero.get(g, []):
            usados[g] += 1
    nuevos = 0
    for tipo, (n, _) in sorted(estadisticas.items(), key=lambda x: -x[1][0]):
        if tipo not in tipos:
            g = adivinar_genero(tipo, generos)
            lista = por_genero.get(g) or por_genero["M"] or [voces[0][0]]
            tipos[tipo] = {"genero": g, "voz": lista[usados.get(g, 0) % len(lista)],
                           "estilo": "", "efecto": adivinar_efecto(tipo)}
            usados[g] = usados.get(g, 0) + 1
            nuevos += 1
        if not tipos[tipo].get("modelo"):
            tipos[tipo]["modelo"] = modelo_de(tipo, None, cfg)
        tipos[tipo]["lineas"] = n
        tipos[tipo]["ejemplo"] = ejemplos.get(tipo, "")[:120]
    orden = sorted(tipos.items(), key=lambda x: -x[1].get("lineas", 0))
    datos = {
        "_explicacion": (
            "Una entrada por tipo de voz del juego. 'voz': id de la voz de Gemini (ver voces_catalogo.json "
            "y la carpeta muestras_voces). 'estilo': instrucción corta en inglés para todo el personaje "
            "(p. ej. 'smug, fast-talking'); vacío suele dar mejor resultado. 'efecto': '', 'robot', "
            "'robot_suave', 'mutante', 'necrofago' o 'radio'. 'modelo': " + FLASH + " (principales) o "
            + FLASH_LITE + " (NPC, más barato). 'lineas' y 'ejemplo' son solo informativos. "
            "Si cambias 'voz', 'estilo' o 'modelo', ese tipo se vuelve a generar (y a pagar); 'efecto' es gratis."
        ),
        "voces_del_catalogo_holandes": del_catalogo,
        "tipos": dict(orden),
    }
    guardar_json(ARCHIVO_TIPOS, datos)
    return nuevos, del_catalogo, tipos


# ---------------------------------------------------------------- Gemini TTS

class Limitador:
    def __init__(self, rpm):
        self.pausa = 60.0 / max(1, rpm)
        self.lock = threading.Lock()
        self.siguiente = 0.0

    def esperar(self):
        with self.lock:
            ahora = time.time()
            turno = max(ahora, self.siguiente)
            self.siguiente = turno + self.pausa
        if turno > ahora:
            time.sleep(turno - ahora)


def _buscar_audio(nodo, encontrados):
    if isinstance(nodo, dict):
        if nodo.get("type") == "audio" and isinstance(nodo.get("data"), str):
            encontrados.append(nodo["data"])
        for k, v in nodo.items():
            if k == "output_audio" and isinstance(v, dict) and isinstance(v.get("data"), str):
                encontrados.append(v["data"])
            else:
                _buscar_audio(v, encontrados)
    elif isinstance(nodo, list):
        for v in nodo:
            _buscar_audio(v, encontrados)


def pcm_a_wav(pcm, hz=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(hz)
        w.writeframes(pcm)
    return buf.getvalue()


def tts_gemini(texto, voz, estilo, cfg, limitador, modelo=None):
    """Devuelve (wav, None) o (None, motivo). Lanza ErrorFatal si no tiene sentido seguir."""
    import requests
    modelo = modelo or cfg["tts_modelo"]
    contenido = {"type": "text", "text": texto}
    if estilo:
        contenido["annotations"] = [{"type": "speech_metadata", "style": estilo}]
    cuerpo = {
        "model": modelo,
        "input": [{"type": "user_input", "content": [contenido]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voz}]},
    }
    headers = {"x-goog-api-key": cfg["gemini_clave"], "Content-Type": "application/json"}
    for intento in range(8):
        limitador.esperar()
        try:
            r = requests.post(f"{API}/interactions", headers=headers, json=cuerpo, timeout=180)
        except requests.RequestException as e:
            print(f"   Sin conexión con Gemini ({e.__class__.__name__}). Reintento en 30 s...")
            time.sleep(30)
            continue
        if r.status_code == 429:
            detalle = r.text.lower()
            if "perday" in detalle or "per day" in detalle:
                raise LimiteDiario(modelo)
            time.sleep(20 * (intento + 1))
            continue
        if r.status_code in (500, 502, 503, 504):
            time.sleep(20 * (intento + 1))
            continue
        if r.status_code in (401, 403):
            raise ErrorFatal("Gemini rechazó la clave. Revisa 'gemini_clave' en config.json.")
        if r.status_code == 404:
            raise ErrorFatal(f"Gemini no reconoce el modelo '{modelo}' (error 404): {r.text[:300]}")
        if r.status_code == 400:
            detalle = r.text.lower()
            if "voice" in detalle:
                raise ErrorFatal(f"Gemini no acepta la voz '{voz}' con {modelo}: {r.text[:400]}")
            if any(p in detalle for p in ("safety", "blocked", "prohibited")):
                return None, "bloqueado por los filtros de Gemini"
            raise ErrorFatal(f"Gemini devolvió el error 400: {r.text[:500]}")
        if r.status_code != 200:
            raise ErrorFatal(f"Gemini devolvió el error {r.status_code}: {r.text[:500]}")
        try:
            encontrados = []
            _buscar_audio(r.json(), encontrados)
        except ValueError:
            encontrados = []
        if not encontrados:
            if intento < 1:
                continue
            return None, "respuesta sin audio"
        datos = base64.b64decode(encontrados[-1])
        return (datos if datos[:4] == b"RIFF" else pcm_a_wav(datos)), None
    raise ErrorFatal("Gemini sigue sin responder. Espera un rato y vuelve a ejecutar.")


def tts_simulado(texto, voz, estilo, cfg, limitador, modelo=None):
    segundos = 0.4 + len(texto) / CARACTERES_POR_SEGUNDO
    return pcm_a_wav(b"\x00\x00" * int(24000 * segundos)), None


def duracion_wav(datos):
    with wave.open(io.BytesIO(datos)) as w:
        return w.getnframes() / w.getframerate(), w.getframerate()


def motivo_audio(texto, segundos):
    if segundos < 0.25 + len(texto) / 40:
        return f"audio demasiado corto ({segundos:.1f} s)"
    if segundos > 3 + len(texto) / 5:
        return f"audio demasiado largo ({segundos:.1f} s)"
    return None


def coste(segundos, cfg, modelo=None):
    return segundos * TOKENS_POR_SEGUNDO * precio(modelo or cfg["tts_modelo"], cfg) / 1e6


def segundos_estimados(texto):
    return 0.4 + len(texto) / CARACTERES_POR_SEGUNDO


# ---------------------------------------------------------------- conversión a .ogg

def comprobar_ffmpeg():
    if not shutil.which("ffmpeg"):
        raise ErrorFatal("No encuentro ffmpeg. Instálalo con:  winget install Gyan.FFmpeg\n"
                         "y abre una terminal nueva.")


def formato_original(bsa, rutas):
    """Frecuencia y canales de un audio original (para que los nuevos sean iguales)."""
    if not shutil.which("ffprobe"):
        return 44100, 1
    for ruta in rutas[:5]:
        try:
            datos = bsa.extraer(ruta)
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                                "stream=sample_rate,channels", "-of", "json", "-"],
                               input=datos, capture_output=True, timeout=30)
            s = json.loads(r.stdout)["streams"][0]
            return int(s["sample_rate"]), int(s["channels"])
        except Exception:
            continue
    return 44100, 1


def convertir(wav, destino, efecto, hz_salida, canales, cfg):
    hz = duracion_wav(wav.read_bytes())[1]
    filtro = EFECTOS.get(efecto or "", "").format(hz=hz, hz_082=int(hz * 0.82), hz_094=int(hz * 0.94))
    cadena = ",".join(x for x in (filtro, f"loudnorm=I={cfg['tts_volumen_lufs']}:TP=-2:LRA=11",
                                  f"aresample={hz_salida}") if x)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp.ogg")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af", cadena,
                        "-ac", str(canales), "-c:a", "libvorbis", "-q:a", "5", str(tmp)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        return r.stderr.strip()[-300:] or "error de ffmpeg"
    tmp.replace(destino)
    return None


# ---------------------------------------------------------------- comandos

def comando_catalogo(cfg, idiomas):
    import requests
    if not tiene_clave(cfg):
        raise ErrorFatal("Falta 'gemini_clave' en config.json.")
    voces, token = [], None
    while True:
        params = [("language_code", i) for i in idiomas] + [("page_size", "1000")]
        if token:
            params.append(("page_token", token))
        r = requests.get(f"{API}/voices", params=params,
                         headers={"x-goog-api-key": cfg["gemini_clave"]}, timeout=60)
        if r.status_code != 200:
            raise ErrorFatal(f"No pude leer el catálogo de voces (error {r.status_code}): {r.text[:300]}\n"
                             "Se usarán las 30 voces base multilingües.")
        datos = r.json()
        for v in datos.get("voices", []):
            vid = v.get("id") or (v.get("name") or "").split("/")[-1]
            if not vid:
                continue
            genero = (v.get("gender") or "?").lower()
            voces.append({
                "id": vid,
                "nombre": v.get("display_name") or v.get("displayName") or vid,
                "genero": {"female": "F", "male": "M"}.get(genero, "?"),
                "tono": v.get("pitch", ""),
                "acento": v.get("accent", ""),
                "idioma": v.get("language_code") or v.get("languageCode", ""),
                "tipo": v.get("type", ""),
                "descripcion": v.get("description", ""),
            })
        token = datos.get("next_page_token") or datos.get("nextPageToken")
        if not token:
            break
    voces = [v for v in voces if v["tipo"] not in ("prompted", "replicated")] + \
            [v for v in voces if v["tipo"] in ("prompted", "replicated")]
    if not voces:
        raise ErrorFatal(f"El catálogo no tiene voces para {', '.join(idiomas)}. "
                         "Se usarán las 30 voces base multilingües.")
    guardar_json(ARCHIVO_CATALOGO, voces)
    print(f"\n{len(voces)} voces ({', '.join(idiomas)}) guardadas en {ARCHIVO_CATALOGO.name}:\n")
    for v in voces:
        print(f"  {v['genero']}  {v['id']:<32} {v['tono']:<7} {v['acento']:<12} {v['descripcion'][:60]}")
    print("\nSiguiente: python voces_fnv.py muestras   (una frase con cada voz, para escucharlas)\n")


def comando_muestras(cfg, texto, genero, simular, modelo):
    if not simular and not tiene_clave(cfg):
        raise ErrorFatal("Falta 'gemini_clave' en config.json.")
    modelo = modelo or cfg["tts_modelo"]
    voces, del_catalogo = voces_disponibles()
    if genero:
        voces = [v for v in voces if v[1] == genero.upper()]
    carpeta = CARPETA_MUESTRAS if modelo == FLASH else CARPETA_MUESTRAS / modelo
    carpeta.mkdir(parents=True, exist_ok=True)
    funcion = tts_simulado if simular else tts_gemini
    limitador = Limitador(cfg["tts_rpm"])
    total = 0.0
    print(f"\nGenerando la frase de prueba con {len(voces)} voces y {modelo} "
          f"({'catálogo holandés' if del_catalogo else 'voces base multilingües'})...")
    for vid, g, desc in voces:
        destino = carpeta / f"{g}_{re.sub(r'[^A-Za-z0-9_-]', '_', vid)}.wav"
        if destino.exists():
            continue
        wav, problema = funcion(texto, vid, "", cfg, limitador, modelo)
        if problema:
            print(f"   {vid}: {problema}")
            continue
        destino.write_bytes(wav)
        total += duracion_wav(wav)[0]
        print(f"   {destino.name}")
    print(f"\nMuestras en {carpeta}  (coste aprox.: {coste(total, cfg, modelo):.3f} USD)")
    print("Escúchalas y pon las que te gusten en voces_tipos.json (campo 'voz').\n")


def comando_probar(cfg, texto, voz, estilo, efecto, simular, modelo):
    comprobar_ffmpeg()
    if not simular and not tiene_clave(cfg):
        raise ErrorFatal("Falta 'gemini_clave' en config.json.")
    modelo = modelo or cfg["tts_modelo"]
    funcion = tts_simulado if simular else tts_gemini
    wav, problema = funcion(texto, voz, estilo, cfg, Limitador(cfg["tts_rpm"]), modelo)
    if problema:
        raise ErrorFatal(problema)
    sufijo = "" if modelo == FLASH else "_lite" if modelo == FLASH_LITE else "_" + re.sub(r"\W", "_", modelo)
    ruta_wav = CARPETA / f"prueba_voz{sufijo}.wav"
    ruta_wav.write_bytes(wav)
    error = convertir(ruta_wav, CARPETA / f"prueba_voz{sufijo}.ogg", efecto, 44100, 1, cfg)
    if error:
        raise ErrorFatal(f"ffmpeg: {error}")
    segundos = duracion_wav(wav)[0]
    print(f"\n{ruta_wav.name} (sin efecto) y prueba_voz{sufijo}.ogg (efecto '{efecto}'), {modelo}: "
          f"{segundos:.1f} s, {coste(segundos, cfg, modelo):.4f} USD\n")


def emparejar(ruta_bsa, ruta_voces, filtros, tipos_elegidos):
    bsa = ArchivoBSA(ruta_bsa)
    archivos, otros = archivos_de_voz(bsa)
    if not archivos:
        raise ErrorFatal(f"No hay voces de FalloutNV.esm en {bsa.ruta.name}. "
                         "¿Es 'Fallout - Voices1.bsa'?")
    lineas, generos = leer_voces(ruta_voces)
    filtros = [f.lower() for f in filtros or []]
    tipos_elegidos = {t.lower() for t in tipos_elegidos or []}
    emparejados, sin_texto = [], []      # sin_texto: [(ruta, tipo, formid, número, motivo, inglés)]
    for ruta, tipo, formid, numero in archivos:
        linea = lineas.get((formid, numero))
        if filtros and not any(f in ruta or (linea and f in linea["mision"].lower()) for f in filtros):
            continue
        if tipos_elegidos and tipo not in tipos_elegidos:
            continue
        if linea is None:
            sin_texto.append((ruta, tipo, formid.upper(), numero, "no está en voces_nl.txt", ""))
            continue
        texto = texto_para_voz(linea["nl"])
        if not texto:
            continue
        # El .esp lleva los temas completos: las frases que no se tradujeron están en inglés.
        # Una voz holandesa leyendo inglés suena peor que el audio original, así que se saltan.
        if linea["en"] and texto == texto_para_voz(linea["en"]):
            sin_texto.append((ruta, tipo, formid.upper(), numero, "sin traducir (igual que en inglés)",
                              linea["en"]))
            continue
        emparejados.append((ruta, tipo, linea, texto))
    return bsa, archivos, otros, emparejados, sin_texto, generos


def nombre_corto(modelo):
    return {FLASH: "Flash", FLASH_LITE: "Lite"}.get(modelo, modelo)


def comando_contar(cfg, ruta_bsa, ruta_voces, filtros, tipos_elegidos):
    bsa, archivos, otros, emparejados, sin_texto, generos = emparejar(
        ruta_bsa, ruta_voces, filtros, tipos_elegidos)
    estadisticas, ejemplos = {}, {}
    for _, tipo, linea, texto in emparejados:
        e = estadisticas.setdefault(tipo, [0, 0])
        e[0] += 1
        e[1] += len(texto)
        ejemplos.setdefault(tipo, texto)
    if not (filtros or tipos_elegidos):
        nuevos, del_catalogo, tipos_cfg = actualizar_tipos(estadisticas, generos, ejemplos, cfg)
    else:
        nuevos, del_catalogo = 0, bool(leer_json(ARCHIVO_CATALOGO, []))
        tipos_cfg = leer_json(ARCHIVO_TIPOS, {}).get("tipos", {})

    caracteres = sum(len(t) for *_, t in emparejados)
    unicos = {(tipo, t) for _, tipo, _, t in emparejados}
    segundos = sum(segundos_estimados(t) for _, t in unicos)
    por_modelo = {}            # modelo -> [audios, segundos, tipos]
    for tipo, t in unicos:
        m = modelo_de(tipo, tipos_cfg.get(tipo), cfg)
        d = por_modelo.setdefault(m, [0, 0.0, set()])
        d[0] += 1
        d[1] += segundos_estimados(t)
        d[2].add(tipo)

    print(f"\n{bsa.ruta.name}: {len(archivos):,} audios de diálogo de FalloutNV.esm")
    if filtros or tipos_elegidos:
        print(f"Filtro: {' '.join(filtros or [])} {' '.join(tipos_elegidos or [])}")
    print(f"  Con texto en holandés:       {len(emparejados):,}  ({caracteres:,} caracteres)")
    n_falta = sum(1 for x in sin_texto if x[4].startswith("no está"))
    print(f"  Sin texto holandés:          {len(sin_texto):,}  (conservan el audio original en inglés)")
    print(f"     - no están en voces_nl.txt:      {n_falta:,}")
    print(f"     - texto igual que en inglés:     {len(sin_texto) - n_falta:,}")
    if sin_texto:
        ruta_csv = escribir_csv(CARPETA / "voces_sin_texto.csv",
                                ["archivo", "tipo", "formid_info", "respuesta", "motivo", "ingles"], sin_texto)
        print(f"     Lista completa: {ruta_csv.name}")
    if otros:
        print(f"  Con otro formato de nombre:  {otros:,}  (no se tocan)")
    print(f"  Audios distintos a generar:  {len(unicos):,}  (frases repetidas dentro de un mismo tipo de voz"
          " se generan una vez)")
    print(f"  Tipos de voz:                {len(estadisticas)}")
    print(f"\nAudio estimado: {segundos / 3600:,.1f} horas")
    print("Con el modelo asignado a cada tipo (voces_tipos.json); +10-20 % por reintentos:")
    total = 0.0
    for m, (n, s, ts) in sorted(por_modelo.items(), key=lambda x: -x[1][1]):
        c = coste(s, cfg, m)
        total += c
        print(f"  {m:<28} {len(ts):>4} tipos {n:>8,} audios {s / 3600:>7.1f} h {c:>9.2f} USD")
    print(f"  {'TOTAL':<28} {'':>4}       {len(unicos):>8,} audios {segundos / 3600:>7.1f} h {total:>9.2f} USD"
          "   (x2 desde 2027)")
    print("Todo con un solo modelo:")
    for m in (FLASH, FLASH_LITE):
        print(f"  {m:<28} {coste(segundos, cfg, m):>9.2f} USD")
    print("\nTipos de voz con más líneas:")
    for tipo, (n, c) in sorted(estadisticas.items(), key=lambda x: -x[1][0])[:25]:
        m = nombre_corto(modelo_de(tipo, tipos_cfg.get(tipo), cfg))
        print(f"  {tipo:<28}{n:>7,} líneas {c:>10,} caracteres  {m}")
    principales = sorted((t for t in estadisticas if modelo_de(t, tipos_cfg.get(t), cfg) != cfg["tts_modelo_npc"]),
                         key=lambda t: -estadisticas[t][0])
    print(f"\nTipos con modelo de principales ({len(principales)}): "
          + (", ".join(principales[:40]) + (" ..." if len(principales) > 40 else "") if principales else "ninguno"))
    if not (filtros or tipos_elegidos):
        print(f"\n{ARCHIVO_TIPOS.name}: {nuevos} tipos nuevos con voz asignada automáticamente "
              f"({'catálogo holandés' if del_catalogo else 'voces base: ejecuta antes catalogo'}).")
        print("Revísalo: género, voz, estilo, efecto y modelo de cada tipo.")
    print()


def comando_generar(cfg, ruta_bsa, ruta_voces, filtros, tipos_elegidos, limite, max_dolares,
                    simular, rehacer):
    comprobar_ffmpeg()
    if not simular and not tiene_clave(cfg):
        raise ErrorFatal("Falta 'gemini_clave' en config.json.")
    tipos_cfg = leer_json(ARCHIVO_TIPOS, {}).get("tipos", {})
    if not tipos_cfg:
        raise ErrorFatal("No existe voces_tipos.json. Ejecuta primero 'contar' (sin filtro).")
    bsa, _, _, emparejados, sin_texto, _ = emparejar(ruta_bsa, ruta_voces, filtros, tipos_elegidos)
    if not emparejados:
        raise ErrorFatal("Ninguna línea coincide con el filtro.")

    sufijo = "_SIMULADO" if simular else ""
    cache = CARPETA / f"cache_voces{sufijo}"
    salida = CARPETA / f"salida_voces{sufijo}"
    hz_salida, canales = formato_original(bsa, [r for r, *_ in emparejados])
    print(f"\n{len(emparejados):,} líneas. Formato de los originales: {hz_salida} Hz, {canales} canal(es).")

    def clave_de(modelo, voz, estilo, texto):
        return hashlib.sha1(f"{modelo}|{voz}|{estilo}|{texto}".encode()).hexdigest()[:24]

    # Agrupar por audio: muchas líneas comparten modelo, voz, estilo y texto.
    trabajos = {}   # clave -> {texto, voz, estilo, modelo, alternativa, destinos: [(ogg, efecto)]}
    sin_voz = set()
    for ruta, tipo, linea, texto in emparejados:
        t = tipos_cfg.get(tipo)
        if not t or not t.get("voz"):
            sin_voz.add(tipo)
            continue
        estilo = estilo_de(linea, t)
        modelo = modelo_de(tipo, t, cfg)
        clave = clave_de(modelo, t["voz"], estilo, texto)
        # Si este audio ya se hizo con Flash (p. ej. antes de pasar los NPC a Lite), se reutiliza.
        alternativa = clave_de(FLASH, t["voz"], estilo, texto) if modelo != FLASH else None
        destino = salida / Path(*ruta.split("\\")).with_suffix(".ogg")
        j = trabajos.setdefault(clave, {"texto": texto, "voz": t["voz"], "estilo": estilo, "modelo": modelo,
                                        "alternativa": alternativa, "destinos": [], "en": linea["en"],
                                        "tipo": tipo})
        j["destinos"].append((destino, t.get("efecto", "")))
    if sin_voz:
        print(f"Sin voz asignada en voces_tipos.json (se saltan): {', '.join(sorted(sin_voz))}")

    def ruta_cache(clave):
        return cache / clave[:2] / f"{clave}.wav"

    def wav_de(clave):
        """El .wav que hay en caché para este trabajo (el del modelo asignado o, si no, el de Flash)."""
        propio = ruta_cache(clave)
        alt = trabajos[clave]["alternativa"]
        if not propio.exists() and alt and ruta_cache(alt).exists():
            return ruta_cache(alt)
        return propio

    pendientes = [c for c in trabajos if not wav_de(c).exists()]
    if limite:
        pendientes = pendientes[:limite]
    estimado = sum(coste(segundos_estimados(trabajos[c]["texto"]), cfg, trabajos[c]["modelo"]) for c in pendientes)
    modelos_pend = {}
    for c in pendientes:
        modelos_pend[trabajos[c]["modelo"]] = modelos_pend.get(trabajos[c]["modelo"], 0) + 1
    print(f"Audios distintos: {len(trabajos):,} (en caché: {len(trabajos) - len(pendientes):,}, "
          f"por generar: {len(pendientes):,}, ~{estimado:.2f} USD)")
    if not simular:
        print("Por modelo: " + ", ".join(f"{m} {n:,}" for m, n in sorted(modelos_pend.items())))
    print(f"Modelo: {'SIMULADO (sin coste)' if simular else 'el de cada tipo en voces_tipos.json'}. "
          f"Tope de gasto de esta ejecución: {max_dolares:.2f} USD\n")

    uso = leer_json(ARCHIVO_USO, {})
    uso.setdefault("gemini_tts_segundos", {})
    uso.setdefault("gemini_tts_usd", {})
    funcion = tts_simulado if simular else tts_gemini
    limitadores = {}            # cada modelo tiene su propio límite de peticiones por minuto
    for c in pendientes:
        limitadores.setdefault(trabajos[c]["modelo"], Limitador(cfg["tts_rpm"]))
    problemas = []
    agotados = set()          # modelos que ya llegaron a su límite diario
    gastado = 0.0
    generados = 0
    detenido = None
    lock_conv = threading.Lock()
    convertidos = [0]
    errores_ffmpeg = []

    def convertir_trabajo(clave):
        j = trabajos[clave]
        for destino, efecto in j["destinos"]:
            if destino.exists() and not rehacer:
                continue
            error = convertir(wav_de(clave), destino, efecto, hz_salida, canales, cfg)
            with lock_conv:
                if error:
                    errores_ffmpeg.append((str(destino), error))
                else:
                    convertidos[0] += 1

    hilos = max(1, int(cfg["tts_hilos"]))
    conversor = concurrent.futures.ThreadPoolExecutor(max_workers=hilos)
    conversiones = [conversor.submit(convertir_trabajo, c) for c in trabajos if wav_de(c).exists()]

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=hilos) as pool:
            cola = list(pendientes)
            while cola:
                if gastado >= max_dolares:
                    detenido = (f"Tope de gasto alcanzado ({gastado:.2f} USD). Sube --max-dolares "
                                "para continuar; lo generado está guardado.")
                    break
                cola = [c for c in cola if trabajos[c]["modelo"] not in agotados]
                if not cola:
                    break
                bloque, cola = cola[:hilos * 5], cola[hilos * 5:]
                futuros = {pool.submit(funcion, trabajos[c]["texto"], trabajos[c]["voz"], trabajos[c]["estilo"],
                                       cfg, limitadores[trabajos[c]["modelo"]], trabajos[c]["modelo"]): c
                           for c in bloque}
                for fut in concurrent.futures.as_completed(futuros):
                    clave = futuros[fut]
                    j = trabajos[clave]
                    try:
                        wav, problema = fut.result()
                    except LimiteDiario as e:
                        if e.modelo not in agotados:
                            agotados.add(e.modelo)
                            print(f"   Límite diario de {e.modelo} alcanzado: sigo solo con los demás modelos.")
                        continue
                    if wav is not None:
                        segundos = duracion_wav(wav)[0]
                        c_audio = coste(segundos, cfg, j["modelo"])
                        gastado += c_audio
                        uso["gemini_tts_segundos"][hoy()] = uso["gemini_tts_segundos"].get(hoy(), 0) + segundos
                        uso["gemini_tts_usd"][hoy()] = uso["gemini_tts_usd"].get(hoy(), 0) + c_audio
                        problema = motivo_audio(j["texto"], segundos)
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
                                          str(j["destinos"][0][0].relative_to(salida))))
                if not simular:
                    guardar_json(ARCHIVO_USO, uso)
                print(f"   {generados:,} audios nuevos · {gastado:.2f} USD")
    except KeyboardInterrupt:
        detenido = "Interrumpido con Ctrl+C. Lo generado está guardado; vuelve a ejecutar para continuar."
    except ErrorFatal as e:
        detenido = f"{e}\nLo generado hasta ahora está guardado; al volver a ejecutar, continúa."
    if agotados and not detenido:
        detenido = (f"Límite diario alcanzado: {', '.join(sorted(agotados))}. Vuelve a ejecutar mañana: "
                    "continúa donde se quedó.")

    print("\nConvirtiendo a .ogg...")
    for c in conversiones:
        c.result()
    conversor.shutdown()

    if problemas:
        ruta_prob = escribir_csv(CARPETA / f"voces_problemas{sufijo}.csv",
                                 ["tipo", "voz", "modelo", "motivo", "holandes", "ingles", "archivo"], problemas)
    print("\n" + "=" * 64)
    print(f"Audios generados en esta ejecución: {generados:,}  ({gastado:.2f} USD aprox.)")
    print(f"Archivos .ogg escritos:             {convertidos[0]:,}")
    print(f"Carpeta para el juego:              {salida / 'sound'}")
    if problemas:
        print(f"Con problemas (se reintentan):      {len(problemas)}  -> {ruta_prob.name}")
    if errores_ffmpeg:
        print(f"Errores de ffmpeg:                  {len(errores_ffmpeg)}  (primero: {errores_ffmpeg[0][1]})")
    if detenido:
        print("\n" + detenido)
    print("=" * 64 + "\n")


def main():
    p = argparse.ArgumentParser(description="Voces en holandés para Fallout: New Vegas con Gemini TTS.")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("catalogo", help="Descarga la lista de voces holandesas de Gemini")
    s.add_argument("--idioma", nargs="+", help="Códigos de idioma (por defecto los de config.json)")

    s = sub.add_parser("muestras", help="Genera una frase de prueba con cada voz")
    s.add_argument("--texto", default=FRASE_MUESTRA)
    s.add_argument("--genero", choices=["F", "M", "f", "m"])
    s.add_argument("--modelo", help=f"{FLASH} (por defecto) o {FLASH_LITE}")
    s.add_argument("--simular", action="store_true")

    s = sub.add_parser("probar", help="Genera una frase con una voz, estilo y efecto concretos")
    s.add_argument("texto")
    s.add_argument("--voz", default="Algenib")
    s.add_argument("--estilo", default="")
    s.add_argument("--efecto", default="", choices=sorted(EFECTOS))
    s.add_argument("--modelo", help=f"{FLASH} (por defecto) o {FLASH_LITE}")
    s.add_argument("--simular", action="store_true")

    for nombre, ayuda in (("contar", "Cuenta líneas y estima el coste; crea voces_tipos.json"),
                          ("generar", "Genera las voces y los .ogg")):
        s = sub.add_parser(nombre, help=ayuda)
        s.add_argument("bsa", type=Path, help='"...\\Data\\Fallout - Voices1.bsa"')
        s.add_argument("voces", type=Path, help='"...\\Edit Scripts\\voces_nl.txt"')
        s.add_argument("--filtro", nargs="+", help="Solo rutas o misiones que contengan estos textos")
        s.add_argument("--tipos", nargs="+", help="Solo estos tipos de voz")
        if nombre == "generar":
            s.add_argument("--limite", type=int, default=0, help="Generar como mucho N audios nuevos")
            s.add_argument("--max-dolares", type=float, default=5.0,
                           help="Detenerse al gastar esta cantidad en esta ejecución (por defecto 5)")
            s.add_argument("--simular", action="store_true", help="Audio en silencio, sin usar la API")
            s.add_argument("--rehacer", action="store_true",
                           help="Volver a convertir los .ogg que ya existen (p. ej. tras cambiar un efecto)")

    a = p.parse_args()
    cfg = leer_config()
    try:
        if a.comando == "catalogo":
            comando_catalogo(cfg, a.idioma or cfg["tts_idiomas"])
        elif a.comando == "muestras":
            comando_muestras(cfg, a.texto, a.genero, a.simular, a.modelo)
        elif a.comando == "probar":
            comando_probar(cfg, a.texto, a.voz, a.estilo, a.efecto, a.simular, a.modelo)
        elif a.comando == "contar":
            comando_contar(cfg, a.bsa, a.voces, a.filtro, a.tipos)
        else:
            comando_generar(cfg, a.bsa, a.voces, a.filtro, a.tipos, a.limite, a.max_dolares,
                            a.simular, a.rehacer)
    except ErrorFatal as e:
        sys.exit(f"\nError: {e}")


if __name__ == "__main__":
    main()