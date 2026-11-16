#!/usr/bin/env python3
"""
voces_fnv_vertex.py
Igual que voces_fnv.py, pero las voces se generan a través de Vertex AI (Google Cloud), para que
se paguen con los créditos de Google Cloud (los $300 del "GCP Free Credit") en lugar del saldo de
AI Studio.

No reemplaza a voces_fnv.py: lo necesita en la misma carpeta y reutiliza TODO lo suyo (lectura del
BSA, voces_tipos.json, caché, efectos, conversión a .ogg, cálculo de costes). Lo único que cambia es
la función que pide el audio a Gemini.

Los comandos son los mismos:
  python voces_fnv_vertex.py probar "Oorlog. Oorlog verandert nooit." --voz Kore --estilo angry
  python voces_fnv_vertex.py muestras
  python voces_fnv_vertex.py contar  BSA VOCES
  python voces_fnv_vertex.py generar BSA VOCES --filtro vcg01 --max-dolares 1

Diferencias con la versión de AI Studio:
  - No usa 'gemini_clave'. Se identifica con las credenciales de gcloud
    (gcloud auth application-default login).
  - Desde el 12/11/2026 el estilo va en un campo aparte (speech_metadata.style de Gemini 3.8 TTS), que
    no se lee en voz alta (BG3: 0 de 10). Antes iba en el texto como [angry tone] "frase".
    "tts_formato_tono": true en config.json vuelve al método antiguo.
  - Se pide holandés (language_code nl-NL).
  - Comprobación automática: duración, y las tomas CON estilo se transcriben (gemini-3.8-flash, diciendo
    que es holandés): se repiten si se oye el estilo o si la frase salió cortada. 3 intentos con estilo
    y 1 sin. "tts_verificar": false en config.json lo desactiva.
  - Opcional "tts_notas_ingles": true -> las notas para el actor del texto inglés ({Dumbfounded},
    {Drunk}...) se añaden al estilo. OJO: cambia el estilo = audio nuevo (se paga) en las líneas con
    nota. Pensado para los DLC que faltan, no para rehacer el juego base.
  - Filtros de seguridad de Gemini al mínimo (BLOCK_NONE): es diálogo de un videojuego.
  - Acepta las 30 voces base y las del catálogo holandés (nl-nl-concierge-1...).
  - La caché (cache_voces) es compartida con voces_fnv.py.

Opcional en config.json:
  "vertex_proyecto": "",
  "vertex_region": "global"          (si un modelo da error 404, prueba "us-central1")

Necesita además: pip install -U google-genai
"""

import base64
import re
import threading
import time

import voces_fnv as base
from voces_fnv import ErrorFatal

PROYECTO_DEFECTO = ""
REGION_DEFECTO = "global"
ESTILO_MAX = 40          # caracteres de estilo que se envían (una descripción larga se lee en voz alta)
CATEGORIAS = ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
              "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]

_cliente = None
_lock_cliente = threading.Lock()
_usar_seguridad = [True]  # se desactiva sola si Vertex no acepta BLOCK_NONE


def cliente(cfg):
    """Crea (una sola vez) el cliente de Vertex AI con las credenciales de gcloud."""
    global _cliente
    with _lock_cliente:
        if _cliente is None:
            try:
                from google import genai
            except ImportError:
                raise ErrorFatal("Falta la librería google-genai. Instálala con:  pip install -U google-genai")
            _cliente = genai.Client(
                vertexai=True,
                project=cfg.get("vertex_proyecto") or PROYECTO_DEFECTO,
                location=cfg.get("vertex_region") or REGION_DEFECTO,
            )
    return _cliente


def estilo_corto(estilo):
    """'very angry, Dumbfounded' -> 'very angry Dumbfounded' (máx. ESTILO_MAX caracteres)."""
    partes = [p.strip() for p in (estilo or "").split(",") if p.strip()]
    if not partes:
        return ""
    elegidas = []
    for p in partes:
        if elegidas and len(" ".join(elegidas + [p])) > ESTILO_MAX:
            break
        elegidas.append(p)
    return " ".join(elegidas)[:ESTILO_MAX].strip()


FORMATO_TONO = [False]       # True = método antiguo ([estilo tone] "frase"); lo fija config.json
VERIFICAR = [True]
MODELO_VERIFICAR = "gemini-3.8-flash"


def contenido_para(texto, estilo):
    """Lo que se envía a Vertex. Con estilo: la frase con speech_metadata.style (campo aparte).
    Sin estilo: solo la frase."""
    e = estilo_corto(estilo)
    if not e:
        return texto
    if FORMATO_TONO[0]:
        return f'[{e} tone] "{texto}"'
    return [{"role": "user", "parts": [{"text": texto, "speech_metadata": {"style": e}}]}]


def _hz_de(mime):
    m = re.search(r"rate=(\d+)", mime or "")
    return int(m.group(1)) if m else 24000


def _config(voz):
    from google.genai import types
    seguridad = ([types.SafetySetting(category=c, threshold="BLOCK_NONE") for c in CATEGORIAS]
                 if _usar_seguridad[0] else None)
    return types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            language_code="nl-NL",
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voz)
            )
        ),
        safety_settings=seguridad,
    )


def _llamar(cfg, modelo, contenido, voz, limitador):
    """Una petición a Vertex con reintentos de red. Devuelve (wav, motivo)."""
    from google.genai import errors
    from google.auth import exceptions as errores_auth

    for intento in range(8):
        limitador.esperar()
        try:
            resp = cliente(cfg).models.generate_content(model=modelo, contents=contenido, config=_config(voz))
        except errores_auth.GoogleAuthError as e:
            raise ErrorFatal("No hay credenciales de Google Cloud válidas. Ejecuta:\n"
                             "  gcloud auth application-default login\n"
                             f"({e.__class__.__name__})")
        except errors.ClientError as e:
            detalle = str(e).lower()
            if e.code == 429:
                time.sleep(20 * (intento + 1))
                continue
            if e.code in (401, 403):
                raise ErrorFatal("Vertex rechazó el acceso. Comprueba que la API de Vertex AI está habilitada "
                                 "en el proyecto y repite 'gcloud auth application-default login'.\n"
                                 f"{str(e)[:300]}")
            if e.code == 404:
                raise ErrorFatal(f"Vertex no reconoce el modelo '{modelo}' en la región "
                                 f"'{cfg.get('vertex_region') or REGION_DEFECTO}'. Prueba con "
                                 f"\"vertex_region\": \"us-central1\" en config.json.\n{str(e)[:300]}")
            if e.code == 400:
                if _usar_seguridad[0] and "safety" in detalle and ("threshold" in detalle or "setting" in detalle):
                    _usar_seguridad[0] = False          # Vertex no acepta BLOCK_NONE: sin ajustes
                    print("   (Vertex no acepta desactivar los filtros; sigo con los filtros normales)")
                    continue
                if "voice" in detalle:
                    raise ErrorFatal(f"Vertex no acepta la voz '{voz}' con {modelo}.\n{str(e)[:300]}")
                if any(p in detalle for p in ("safety", "blocked", "prohibited")):
                    return None, "bloqueado por los filtros de Gemini"
                raise ErrorFatal(f"Vertex devolvió el error 400: {str(e)[:500]}")
            raise ErrorFatal(f"Vertex devolvió el error {e.code}: {str(e)[:500]}")
        except errors.ServerError:
            time.sleep(20 * (intento + 1))
            continue
        except ErrorFatal:
            raise
        except Exception as e:                       # cortes de conexión, timeouts...
            print(f"   Sin conexión con Vertex ({e.__class__.__name__}). Reintento en 30 s...")
            time.sleep(30)
            continue

        datos, mime, candidato = None, "", None
        try:
            candidato = resp.candidates[0]
            for parte in candidato.content.parts or []:
                if parte.inline_data and parte.inline_data.data:
                    datos, mime = parte.inline_data.data, parte.inline_data.mime_type or ""
        except (AttributeError, IndexError, TypeError):
            pass
        if not datos:
            razon = str(getattr(candidato, "finish_reason", "") or "").upper()
            bloqueo = str(getattr(getattr(resp, "prompt_feedback", None), "block_reason", "") or "").upper()
            if any(p in razon + bloqueo for p in ("SAFETY", "BLOCK", "PROHIBITED")):
                return None, "bloqueado por los filtros de Gemini"
            return None, "respuesta sin audio"
        if isinstance(datos, str):
            datos = base64.b64decode(datos)
        if datos[:4] == b"RIFF":
            return datos, None
        return base.pcm_a_wav(datos, _hz_de(mime)), None

    raise ErrorFatal("Vertex sigue sin responder. Espera un rato y vuelve a ejecutar.")


def oir(cfg, wav, limitador):
    """Transcripción del audio (gemini-3.8-flash), diciendo que es holandés. None si no contesta."""
    from google.genai import types
    limitador.esperar()
    try:
        resp = cliente(cfg).models.generate_content(
            model=MODELO_VERIFICAR,
            contents=[types.Part.from_bytes(data=wav, mime_type="audio/wav"),
                      "Transcribe this audio exactly as spoken, word for word, from the very first word. The "
                      "speaker speaks Dutch (a name may appear). Do not translate or correct anything; if other "
                      "words are said before or after (for example English instructions), write them too. "
                      "Reply with only the transcription."],
            config=types.GenerateContentConfig(temperature=0,
                                               thinking_config=types.ThinkingConfig(thinking_budget=0)))
        return (resp.text or "").strip() or None
    except Exception as e:
        print(f"   (no se pudo comprobar: {str(e)[:80]})")
        return None


def fallo_de_toma(texto, estilo, oido):
    """'estilo' (se oyen palabras del estilo), 'cortada' (solo el principio de la frase) o None.
    Que el transcriptor oiga otras palabras no cuenta: casi siempre es él quien se equivoca."""
    palabras = {w for w in re.findall(r"[a-z]+", estilo.lower()) if len(w) > 3} | {"tone", "style"}
    palabras -= set(re.findall(r"[a-z]+", texto.lower()))
    oido_l = oido.lower()
    if any(re.search(rf"\b{re.escape(w)}\b", oido_l) for w in palabras):
        return "estilo"
    a = re.findall(r"\w+", texto.lower())
    b = re.findall(r"\w+", oido_l)
    if len(a) >= 4 and b:
        corto = len("".join(b)) / len("".join(a))
        if corto < 0.6 or (corto < 0.7 and a[:min(2, len(b))] == b[:min(2, len(b))]):
            return "cortada"
    return None


def tts_vertex(texto, voz, estilo, cfg, limitador, modelo=None):
    """Igual que tts_gemini de voces_fnv.py, pero por Vertex AI.
    Con estilo: tres intentos con el estilo (speech_metadata) y uno final con la frase sola. Una toma con
    estilo se repite si la duración es rara, si se oye el estilo o si la frase salió cortada.
    Devuelve (wav, None) o (None, motivo). Si todos salen con duración rara, devuelve el último:
    voces_fnv.py lo aparta en cache_voces\\_dudosos y lo apunta en voces_problemas.csv."""
    modelo = modelo or cfg["tts_modelo"]
    intentos = [(contenido_para(texto, estilo), True)] * 3 if estilo_corto(estilo) else [(texto, False)]
    intentos.append((texto, False))
    ultimo, motivo = None, None
    for contenido, con_estilo in intentos:
        wav, motivo = _llamar(cfg, modelo, contenido, voz, limitador)
        if wav is None:
            continue
        if base.motivo_audio(texto, base.duracion_wav(wav)[0]):
            ultimo = wav
            continue
        if con_estilo and VERIFICAR[0]:
            oido = oir(cfg, wav, limitador)
            fallo = fallo_de_toma(texto, estilo_corto(estilo), oido) if oido else None
            if fallo:
                print(f"   {'leyó el estilo' if fallo == 'estilo' else 'frase cortada'} "
                      f"('{oido[:40]}'): se repite")
                ultimo = wav
                continue
        return wav, None
    if ultimo is not None:
        return ultimo, None
    return None, motivo or "respuesta sin audio"


NOTA_INGLES = re.compile(r"\{([^{}]{2,40})\}")


def estilo_con_notas(original):
    """estilo_de de voces_fnv.py + las notas para el actor del texto inglés ({Dumbfounded}, {Drunk}).
    Solo se añaden notas cortas que describen cómo hablar (no las de dirección como {Beat} o {pause})."""
    ignorar = {"beat", "pause", "long pause", "short pause", "sfx", "vo", "laughs", "sighs", "cough"}

    def estilo_de(linea, cfg_tipo):
        estilo = original(linea, cfg_tipo)
        notas = []
        for n in NOTA_INGLES.findall(linea.get("en") or ""):
            n = n.strip().strip(".").lower()
            if n and n not in ignorar and not n.startswith(("beat", "pause")) and n not in estilo.lower():
                notas.append(n)
        if notas:
            estilo = ", ".join([estilo] + notas[:1]) if estilo else notas[0]
        return estilo
    return estilo_de


# ---------------------------------------------------------------- conectar con voces_fnv.py

_probar_original = base.comando_probar


def probar_vertex(cfg, texto, voz, estilo, efecto, simular, modelo):
    """Como 'probar', pero guarda prueba_voz..._vertex.wav/.ogg para no pisar las pruebas de AI Studio."""
    if estilo and not simular:
        print(f'Se envía a Vertex: {contenido_para(texto, estilo)}')
    _probar_original(cfg, texto, voz, estilo, efecto, simular, modelo)
    modelo = modelo or cfg["tts_modelo"]
    sufijo = ("" if modelo == base.FLASH else "_lite" if modelo == base.FLASH_LITE
              else "_" + re.sub(r"\W", "_", modelo))
    for ext in (".wav", ".ogg"):
        origen = base.CARPETA / f"prueba_voz{sufijo}{ext}"
        if origen.exists():
            origen.replace(base.CARPETA / f"prueba_voz{sufijo}_vertex{ext}")
    print(f"(Guardado como prueba_voz{sufijo}_vertex.wav / .ogg)\n")


def archivos_de_voz(bsa):
    """Como en voces_fnv.py, pero acepta la carpeta de voces de cualquier .esm (juego base o DLC:
    sound\\voice\\deadmoney.esm\\...). Así sirve con 'DeadMoney - Main.bsa' y voces_nl_DeadMoney.txt."""
    salida, otros = [], 0
    for ruta in bsa.archivos:
        partes = ruta.split("\\")
        if len(partes) < 5 or partes[:2] != ["sound", "voice"] or not partes[2].endswith(".esm"):
            continue
        m = base.PATRON_VOZ.search(partes[-1])
        if not m:
            if not partes[-1].endswith(".lip"):
                otros += 1
            continue
        salida.append((ruta, partes[-2], m.group(1).lower(), int(m.group(2))))
    return salida, otros


base.archivos_de_voz = archivos_de_voz
base.tts_gemini = tts_vertex                 # todos los comandos piden el audio a Vertex
base.tiene_clave = lambda cfg: True          # Vertex no usa 'gemini_clave'
base.comando_probar = probar_vertex

if __name__ == "__main__":
    _cfg = base.leer_config()
    FORMATO_TONO[0] = bool(_cfg.get("tts_formato_tono", False))
    VERIFICAR[0] = bool(_cfg.get("tts_verificar", True))
    if _cfg.get("tts_notas_ingles", False):
        base.estilo_de = estilo_con_notas(base.estilo_de)
    print("[Vertex AI] proyecto:", _cfg.get("vertex_proyecto") or PROYECTO_DEFECTO,
          "· estilo", "en el texto (antiguo)" if FORMATO_TONO[0] else "en speech_metadata",
          "· notas inglesas" if _cfg.get("tts_notas_ingles", False) else "")
    base.main()
