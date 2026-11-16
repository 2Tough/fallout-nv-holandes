#!/usr/bin/env python3
"""
traducir_fnv.py
Traduce al holandés (NL) el texto de Fallout: New Vegas exportado a XML con xTranslator.

- Diálogos y misiones (INFO, DIAL, QUST)  -> DeepL   (mientras quede cuota)
- Todo lo demás y lo que no quepa en DeepL -> Gemini (si hay clave), si no Microsoft, si no Ollama

Uso (desde la terminal, en la carpeta del script):
  python traducir_fnv.py contar    FalloutNV_en_de.xml              -> cuánto texto queda y quién lo traduce
  python traducir_fnv.py comparar  FalloutNV_en_de.xml --limite 30  -> prueba A/B: DeepL (caché) vs Gemini
  python traducir_fnv.py traducir  FalloutNV_en_de.xml --simular    -> prueba sin gastar nada
  python traducir_fnv.py traducir  FalloutNV_en_de.xml --limite 100 -> traduce solo 100 textos
  python traducir_fnv.py traducir  FalloutNV_en_de.xml --sin-dialogos -> solo objetos, menús, etc.
  python traducir_fnv.py traducir  FalloutNV_en_de.xml              -> traducción completa

Modelos de Gemini (config.json):
  "gemini_modelo"            -> para objetos, menús y demás textos
  "gemini_modelo_dialogos"   -> para diálogos y misiones (vacío = el mismo que gemini_modelo)
  python traducir_fnv.py exportar-xedit FalloutNV_en_de.xml DeadMoney_en_de.xml ...
      -> traducciones_nl.txt y campos_nl.txt para esm_nl.py (admite varios XML: juego base + DLC)

Sin DeepL: deja "deepl_clave": "" en config.json y los diálogos y misiones irán a
"gemini_modelo_dialogos"; el resto a "gemini_modelo".

Las traducciones se guardan en cache_traducciones.json: si el script se corta o lo
vuelves a ejecutar, nunca paga dos veces por el mismo texto.
"""

import argparse
import csv
import datetime
import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
ARCHIVO_CONFIG = CARPETA / "config.json"
ARCHIVO_USO = CARPETA / "uso.json"
ARCHIVO_CACHE = CARPETA / "cache_traducciones.json"
ARCHIVO_GLOSARIO = CARPETA / "glosario.json"

CONFIG_EJEMPLO = {
    "deepl_clave": "PEGA_AQUI_TU_CLAVE_DE_DEEPL",
    "deepl_limite_total": 950000,
    "deepl_tipos": ["INFO", "DIAL", "QUST"],
    "deepl_formalidad": "prefer_less",
    "gemini_clave": "PEGA_AQUI_TU_CLAVE_DE_GEMINI",
    "gemini_modelo": "gemini-3.5-flash-lite",
    "gemini_modelo_dialogos": "",
    "gemini_rpm": 8,
    "gemini_thinking_budget": None,
    "microsoft_clave": "PEGA_AQUI_TU_KEY_1_DE_AZURE",
    "microsoft_region": "westeurope",
    "microsoft_limite_mensual": 1950000,
    "ollama_activado": False,
    "ollama_modelo": "qwen2.5:7b",
    "ollama_max_caracteres": 40,
}

GLOSARIO_EJEMPLO = {
    "_explicacion": (
        "Cada término de la izquierda se reemplaza siempre por el de la derecha y el "
        "traductor no lo toca. Si izquierda y derecha son iguales, el término no se traduce. "
        "Distingue mayúsculas: añade variantes si hace falta (por ejemplo 'caps' y 'Caps')."
    ),
    "terminos": {
        "NCR": "NCR",
        "Mr. House": "Mr. House",
        "New Vegas": "New Vegas",
        "Mojave": "Mojave",
        "Pip-Boy": "Pip-Boy",
        "Vault-Tec": "Vault-Tec",
        "Caesar's Legion": "Caesar's Legion",
        "Courier": "Koerier",
        "caps": "doppen",
    },
}

# Trozos que NUNCA deben traducirse: variables del juego, formatos y saltos de línea.
TOKENS = re.compile(
    r"<[^<>\n]+>"                              # <Alias=Player>, <Global=...>
    r"|%[-+ 0#]*\d*(?:\.\d+)?[sdifgxXc]|%%"    # %s, %d, %.2f, %%
    r"|&[A-Za-z0-9_\-]+;"                      # &PCName; y similares
    r"|\r?\n|\\n"                              # saltos de línea
)

RESTAURAR = {
    "deepl": re.compile(r'<x id="(?P<i>\d+)"\s*/?>(?:\s*</x>)?'),
    "microsoft": re.compile(r'<span class="notranslate">\s*#(?P<i>\d+)#\s*</span>'),
    "plano": re.compile(r"⟦(?P<i>\d+)⟧"),
}

PROMPT_OLLAMA = (
    "You translate short game texts from the video game Fallout: New Vegas from English to Dutch. "
    "Use natural, informal Dutch (je/jij). Keep every token like ⟦0⟧ exactly as it is. "
    "Answer with ONLY the Dutch translation, nothing else."
)

PROMPT_GEMINI = """You translate text from the video game Fallout: New Vegas (English) into Dutch for a Dutch-language mod.
Rules:
- Write natural, informal Dutch (je/jij). Keep each character's tone: slang, humour, threats, Old West and post-apocalyptic flavour.
- Tokens like ⟦0⟧ are game variables or fixed terms. Copy every token exactly, exactly once, in a sensible position. Never translate or change them.
- Translate idioms, slang and profanity by their intended meaning, not word for word, and keep a similar level of vulgarity. Example: "fuck you up with a rocket barrage" means destroying someone, not a sexual act. Example: "deal with them" usually means "handle / cope with them" (omgaan met, aanpakken), not "settle scores" (afrekenen), unless the context is clearly violent.
- Keep Fallout names, ranks and titles in English as written: Elder, Paladin, Scribe, Knight, Legate, Centurion, Old Lady Gibson, Mr. House, etc.
- Translate every entry separately. Never merge, skip, split or add entries. No notes or explanations.
- Keep a similar punctuation style (ellipses, quotation marks, exclamation marks). Short UI texts such as item names and menu labels stay short. Text in ALL CAPS stays in ALL CAPS.
- Input: a JSON object mapping ids to English texts. Output: ONLY a JSON object with exactly the same ids, each mapped to its Dutch translation."""

CATEGORIAS_GEMINI = [
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
]


class ErrorFatal(Exception):
    pass


class CuotaAgotada(Exception):
    pass


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


def preparar_archivos():
    """Crea config.json y glosario.json la primera vez."""
    creados = []
    if not ARCHIVO_CONFIG.exists():
        guardar_json(ARCHIVO_CONFIG, CONFIG_EJEMPLO)
        creados.append(ARCHIVO_CONFIG.name)
    if not ARCHIVO_GLOSARIO.exists():
        guardar_json(ARCHIVO_GLOSARIO, GLOSARIO_EJEMPLO)
        creados.append(ARCHIVO_GLOSARIO.name)
    return creados


def leer_xml(ruta):
    arbol = ET.parse(ruta)
    entradas = []
    for nodo in arbol.getroot().iter("String"):
        fuente = nodo.find("Source")
        if fuente is None or not (fuente.text or "").strip():
            continue
        rec = nodo.find("REC")
        tipo = "?"
        if rec is not None:
            texto_rec = (rec.text or "").strip()
            tipo = texto_rec.split(":")[0] if texto_rec else (rec.get("id") or "?")
        entradas.append((nodo, tipo.upper(), fuente.text))
    if not entradas:
        raise ErrorFatal(
            "No encontré textos en el XML (se esperaban elementos <String> con <Source>). "
            "¿Lo exportaste a XML desde xTranslator? Si el formato es distinto, "
            "copia las primeras 30 líneas del archivo y pide ayuda para ajustar el script."
        )
    return arbol, entradas


def escribir_csv(ruta, cabecera, filas):
    """Escribe un CSV para Excel. Si el archivo está abierto (Excel lo bloquea), usa otro nombre."""
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
            nueva = ruta.with_name(f"{ruta.stem}_{datetime.datetime.now():%H%M%S}{ruta.suffix}")
            print(f"\n   {ruta.name} está abierto en otro programa (¿Excel?). Lo guardo como {nueva.name}.")
            ruta = nueva


def leer_uso():
    uso = leer_json(ARCHIVO_USO, {})
    uso.setdefault("deepl_total", 0)
    uso.setdefault("microsoft", {})
    uso.setdefault("gemini", {})
    return uso


# ---------------------------------------------------------------- protección de variables

def dividir(texto, terminos, saltos=True):
    """Separa el texto en trozos traducibles y trozos protegidos.
    saltos=False deja los saltos de línea reales dentro del texto (para Gemini/Ollama, que los
    conservan bien en JSON; con marcadores se desordenaban en textos de varios párrafos)."""
    spans = [(m.start(), m.end(), m.group(0)) for m in TOKENS.finditer(texto)
             if saltos or m.group(0) not in ("\n", "\r\n")]
    for termino, destino in terminos.items():
        patron = r"(?<![A-Za-z])" + re.escape(termino) + r"(?![A-Za-z])"
        spans += [(m.start(), m.end(), destino) for m in re.finditer(patron, texto)]
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    partes, protegidos, pos = [], [], 0
    for ini, fin, reemplazo in spans:
        if ini < pos:
            continue
        if ini > pos:
            partes.append(texto[pos:ini])
        partes.append(len(protegidos))
        protegidos.append(reemplazo)
        pos = fin
    if pos < len(texto):
        partes.append(texto[pos:])
    return partes, protegidos


def marcar(partes, modo):
    salida = []
    for p in partes:
        if isinstance(p, int):
            if modo == "deepl":
                salida.append(f'<x id="{p}"/>')
            elif modo == "microsoft":
                salida.append(f'<span class="notranslate">#{p}#</span>')
            else:
                salida.append(f"⟦{p}⟧")
        else:
            salida.append(html.escape(p, quote=False) if modo in ("deepl", "microsoft") else p)
    return "".join(salida)


def restaurar(traducido, protegidos, modo):
    """Devuelve el texto final, o None si la traducción rompió algo."""
    patron = RESTAURAR["plano" if modo not in RESTAURAR else modo]
    vistos = []

    def a_marca(m):
        vistos.append(int(m.group("i")))
        return f"\ue000{m.group('i')}\ue001"

    texto = patron.sub(a_marca, traducido)
    if modo in ("deepl", "microsoft"):
        if re.search(r"<[^>]*>", texto):
            return None
        texto = html.unescape(texto)
    # Variables del juego y saltos de línea: obligatorias, exactamente una vez.
    # Términos del glosario (doppen, NCR...): opcionales; el traductor puede omitir o repetir alguno.
    if any(i >= len(protegidos) for i in vistos):
        return None
    requeridos = [i for i, p in enumerate(protegidos) if TOKENS.fullmatch(p)]
    if any(vistos.count(i) != 1 for i in requeridos):
        return None
    return re.sub(r"\ue000(\d+)\ue001", lambda m: protegidos[int(m.group(1))], texto)


# ---------------------------------------------------------------- servicios de traducción

_deepl = None


def traducir_deepl(textos, cfg):
    global _deepl
    import deepl
    if _deepl is None:
        cliente = getattr(deepl, "DeepLClient", None) or deepl.Translator
        _deepl = cliente(cfg["deepl_clave"])
    try:
        res = _deepl.translate_text(
            textos, source_lang="EN", target_lang="NL",
            tag_handling="xml", ignore_tags=["x"],
            formality=cfg.get("deepl_formalidad", "prefer_less"),
        )
    except deepl.AuthorizationException:
        raise ErrorFatal("DeepL rechazó la clave. Revisa 'deepl_clave' en config.json.")
    except deepl.QuotaExceededException:
        raise CuotaAgotada()
    return [r.text for r in res]


_gemini_ultima = 0.0


def _gemini_peticion(textos, cfg):
    """Una petición a Gemini. Devuelve la lista de traducciones, o None si la respuesta no sirve."""
    import requests
    global _gemini_ultima
    modelo = cfg["gemini_modelo"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
    entrada = {str(i + 1): t for i, t in enumerate(textos)}
    generacion = {"temperature": 0.3, "responseMimeType": "application/json"}
    if cfg.get("gemini_thinking_budget") is not None:
        generacion["thinkingConfig"] = {"thinkingBudget": cfg["gemini_thinking_budget"]}
    cuerpo = {
        "systemInstruction": {"parts": [{"text": PROMPT_GEMINI + cfg.get("_prompt_extra", "")}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(entrada, ensure_ascii=False)}]}],
        "generationConfig": generacion,
        # Es texto de un videojuego con violencia y lenguaje fuerte: sin filtros de contenido.
        "safetySettings": [{"category": c, "threshold": "BLOCK_NONE"} for c in CATEGORIAS_GEMINI],
    }
    headers = {"x-goog-api-key": cfg["gemini_clave"], "Content-Type": "application/json"}
    pausa_minima = 60.0 / max(1, cfg.get("gemini_rpm", 8))

    for intento in range(8):
        espera = _gemini_ultima + pausa_minima - time.time()
        if espera > 0:
            time.sleep(espera)
        _gemini_ultima = time.time()
        try:
            r = requests.post(url, headers=headers, json=cuerpo, timeout=300)
        except requests.RequestException as e:
            print(f"   Sin conexión con Gemini ({e.__class__.__name__}). Reintento en 30 s...")
            time.sleep(30)
            continue

        if r.status_code == 429:
            detalle = r.text.lower()
            if "perday" in detalle or "per day" in detalle:
                raise ErrorFatal(
                    "Se alcanzó el límite DIARIO de Gemini. Se reinicia a medianoche hora del Pacífico "
                    "(hacia las 11:00 en Moscú). Vuelve a ejecutar entonces: continúa donde se quedó."
                )
            espera = 20 * (intento + 1)
            print(f"   Gemini pide esperar (demasiadas peticiones por minuto). Pausa de {espera} s...")
            time.sleep(espera)
            continue
        if r.status_code in (500, 502, 503, 504):
            espera = 20 * (intento + 1)
            print(f"   Gemini está saturado (error {r.status_code}). Pausa de {espera} s...")
            time.sleep(espera)
            continue
        if r.status_code in (401, 403) or (r.status_code == 400 and "api key" in r.text.lower()):
            raise ErrorFatal("Gemini rechazó la clave. Revisa 'gemini_clave' en config.json.")
        if r.status_code == 404:
            raise ErrorFatal(f"Gemini no reconoce el modelo '{modelo}'. Revisa 'gemini_modelo' en config.json.")
        if r.status_code == 400:
            raise ErrorFatal(
                f"Gemini devolvió el error 400: {r.text[:400]}\n"
                "Si el mensaje habla de 'thinking', pon \"gemini_thinking_budget\": null en config.json."
            )
        r.raise_for_status()

        try:
            candidato = r.json()["candidates"][0]
            partes = candidato["content"]["parts"]
            texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
            respuesta = json.loads(texto)
            if not isinstance(respuesta, dict):
                raise ValueError
        except (KeyError, IndexError, ValueError, TypeError):
            if intento < 1:
                continue  # un reintento; si vuelve a fallar, se divide el lote
            return None
        return [str(respuesta.get(str(i + 1), "")) for i in range(len(textos))]
    raise ErrorFatal("Gemini sigue sin responder. Espera un rato y vuelve a ejecutar.")


def traducir_gemini(textos, cfg):
    resultado = _gemini_peticion(textos, cfg)
    if resultado is not None:
        return resultado
    if len(textos) == 1:
        return [""]  # irá a *_problemas.csv y se reintentará en la próxima ejecución
    mitad = len(textos) // 2
    return traducir_gemini(textos[:mitad], cfg) + traducir_gemini(textos[mitad:], cfg)


def modelo_dialogos(cfg):
    return (cfg.get("gemini_modelo_dialogos") or "").strip() or cfg["gemini_modelo"]


def traducir_gemini_dialogos(textos, cfg):
    return traducir_gemini(textos, {**cfg, "gemini_modelo": modelo_dialogos(cfg)})


# ---------------------------------------------------------------- comprobaciones de traducciones de IA

CHARLA_IA = re.compile(
    r"(?i)(here is the|here's the|translation\s*:|vertaling\s*:|hier is de vertaling|as an ai|als ai)"
)


PALABRAS_FUNCION = {
    "the", "you", "your", "is", "are", "was", "and", "to", "it", "that", "this", "what", "we",
    "i", "me", "my", "he", "she", "they", "be", "have", "do", "not", "can", "will", "with", "for",
}


def parece_frase_inglesa(texto):
    """True si el texto es una frase normal en inglés que debería traducirse.
    False para nombres propios, títulos, rutas de archivos, notas internas <...>/{...}, risas, etc."""
    if re.search(r"\.(dds|nif|kf|wav|ogg|esp|esm)\b", texto, re.I) or "\\" in texto:
        return False
    resto = re.sub(r"<[^<>]*>|\{[^{}]*\}|\[[^\[\]]*\]", " ", texto)  # quitar notas y etiquetas
    palabras = re.findall(r"[A-Za-z']{2,}", resto)
    if len(palabras) < 4:
        return False
    if not any(p.lower() in PALABRAS_FUNCION for p in palabras):
        return False  # títulos como "Nellis Air Force Base", risas, tecleo aleatorio
    largas = [p for p in palabras if len(p) > 3]
    if largas and sum(p[0].isupper() for p in largas) / len(largas) > 0.7:
        return False  # Title Case: nombres de canciones, misiones, libros, lugares
    return True


def sin_notas(texto):
    """Texto sin las notas para el actor de voz ({Sad}, {Beat}...), sin espacios sobrantes."""
    return re.sub(r"\s+", " ", re.sub(r"\{[^{}]*\}", " ", texto)).strip()


def motivo_sospecha(fuente, final):
    """Detecta errores típicos de un modelo de lenguaje. Devuelve el motivo, o None si parece bien."""
    if final.strip() == fuente.strip() and parece_frase_inglesa(fuente):
        return "sin traducir (igual al inglés)"
    # Los saltos de línea del final no cuentan (a veces el original termina en "\n\n")
    if fuente.strip().count("\n") != final.strip().count("\n"):
        return "saltos de línea distintos (párrafos desordenados)"
    # Las notas para el actor {…} no salen en pantalla y Gemini suele quitarlas: no cuentan
    # para comparar la longitud.
    f, d = sin_notas(fuente), sin_notas(final)
    if len(f) >= 30:
        proporcion = len(d) / len(f)
        if proporcion < 0.5:
            return "demasiado corta (¿traducción a medias?)"
        if proporcion > 2.5:
            return "demasiado larga (¿texto añadido?)"
    if CHARLA_IA.search(final) and not CHARLA_IA.search(fuente):
        return "contiene comentarios del modelo"
    return None


def traducir_microsoft(textos, cfg):
    import requests
    url = "https://api.cognitive.microsofttranslator.com/translate"
    params = {"api-version": "3.0", "from": "en", "to": "nl", "textType": "html"}
    headers = {
        "Ocp-Apim-Subscription-Key": cfg["microsoft_clave"],
        "Ocp-Apim-Subscription-Region": cfg["microsoft_region"],
        "Content-Type": "application/json",
    }
    for intento in range(6):
        r = requests.post(url, params=params, headers=headers,
                          json=[{"Text": t} for t in textos], timeout=90)
        if r.status_code == 429:
            espera = 15 * (intento + 1)
            print(f"   Microsoft pide esperar (demasiadas peticiones). Pausa de {espera} s...")
            time.sleep(espera)
            continue
        if r.status_code in (401, 403):
            raise ErrorFatal("Microsoft rechazó la clave o la región. Revisa config.json.")
        r.raise_for_status()
        return [x["translations"][0]["text"] for x in r.json()]
    raise ErrorFatal("Microsoft sigue limitando las peticiones. Espera un rato y vuelve a ejecutar.")


def traducir_ollama(textos, cfg):
    import requests
    salida = []
    for t in textos:
        try:
            r = requests.post("http://localhost:11434/api/chat", timeout=300, json={
                "model": cfg["ollama_modelo"], "stream": False,
                "options": {"temperature": 0.2},
                "messages": [{"role": "system", "content": PROMPT_OLLAMA},
                             {"role": "user", "content": t}],
            })
        except requests.ConnectionError:
            raise ErrorFatal("No puedo conectar con Ollama. ¿Está abierto? Prueba 'ollama list' en la terminal.")
        r.raise_for_status()
        respuesta = r.json()["message"]["content"].strip()
        if len(respuesta) >= 2 and respuesta[0] == respuesta[-1] == '"' and not t.startswith('"'):
            respuesta = respuesta[1:-1]
        salida.append(respuesta)
    return salida


def traducir_simulado(textos, cfg):
    return ["[NL] " + t for t in textos]


# servicio: (función, modo de marcadores, máx. textos por lote, máx. caracteres por lote)
SERVICIOS = {
    "deepl": (traducir_deepl, "deepl", 40, 30000),
    "gemini_dialogos": (traducir_gemini_dialogos, "plano", 40, 8000),
    "gemini": (traducir_gemini, "plano", 40, 8000),
    "microsoft": (traducir_microsoft, "microsoft", 50, 20000),
    "ollama": (traducir_ollama, "plano", 1, 10**9),
    "simular": (traducir_simulado, "plano", 100, 10**9),
}
ORDEN_SERVICIOS = ["simular", "deepl", "gemini_dialogos", "gemini", "ollama", "microsoft"]
SERVICIOS_IA = {"gemini", "gemini_dialogos", "ollama"}  # se les aplican las comprobaciones extra


# ---------------------------------------------------------------- planificación

def mes_actual():
    return datetime.date.today().strftime("%Y-%m")


def hoy():
    return datetime.date.today().isoformat()


def tiene_letras(texto):
    return re.search(r"[A-Za-z]", texto) is not None


def tiene_clave(cfg, nombre):
    clave = (cfg.get(nombre) or "").strip()
    return bool(clave) and "PEGA_AQUI" not in clave


def tiene_microsoft(cfg):
    return tiene_clave(cfg, "microsoft_clave")


def tiene_gemini(cfg):
    return tiene_clave(cfg, "gemini_clave")


def servicio_de_respaldo(cfg):
    """Servicio para lo que no va a DeepL: Gemini si hay clave; si no, Microsoft; si no, Ollama."""
    if tiene_gemini(cfg):
        return "gemini"
    return "microsoft" if tiene_microsoft(cfg) else "ollama"


def planificar(entradas, cache, cfg, simular):
    """Agrupa los textos únicos pendientes y decide qué servicio traduce cada uno."""
    prioritarios = set(cfg["deepl_tipos"])
    pendientes = {}  # texto -> conjunto de tipos
    for _, tipo, fuente in entradas:
        if fuente in cache or not tiene_letras(fuente):
            continue
        pendientes.setdefault(fuente, set()).add(tipo)
    plan = []
    for fuente, tipos in pendientes.items():
        if simular:
            servicio = "simular"
        elif tipos & prioritarios:
            if tiene_clave(cfg, "deepl_clave"):
                servicio = "deepl"
            else:  # sin DeepL: diálogos y misiones al modelo de diálogos de Gemini
                servicio = "gemini_dialogos" if tiene_gemini(cfg) else servicio_de_respaldo(cfg)
        elif cfg.get("ollama_activado") and len(fuente) <= cfg.get("ollama_max_caracteres", 40):
            servicio = "ollama"
        else:
            servicio = servicio_de_respaldo(cfg)
        plan.append((fuente, servicio))
    return plan


def lotes(items, max_textos, max_chars):
    lote, chars = [], 0
    for item in items:
        n = len(item[1])
        if lote and (len(lote) >= max_textos or chars + n > max_chars):
            yield lote
            lote, chars = [], 0
        lote.append(item)
        chars += n
    if lote:
        yield lote


# ---------------------------------------------------------------- comandos

def comando_contar(ruta_xml, cfg):
    _, entradas = leer_xml(ruta_xml)
    cache = leer_json(ARCHIVO_CACHE, {})
    uso = leer_uso()

    por_tipo = {}
    for _, tipo, fuente in entradas:
        d = por_tipo.setdefault(tipo, [0, 0])
        d[0] += 1
        d[1] += len(fuente)
    print(f"\nArchivo: {ruta_xml.name} — {len(entradas)} líneas de texto\n")
    print(f"{'Tipo':<8}{'Líneas':>10}{'Caracteres':>14}")
    for tipo, (n, c) in sorted(por_tipo.items(), key=lambda x: -x[1][1]):
        motor = "DeepL" if tiene_clave(cfg, "deepl_clave") else "modelo de diálogos"
        marca = f"  <- {motor}" if tipo in cfg["deepl_tipos"] else ""
        print(f"{tipo:<8}{n:>10}{c:>14}{marca}")

    plan = planificar(entradas, cache, cfg, simular=False)
    total = {s: [0, 0] for s in SERVICIOS}
    for fuente, servicio in plan:
        total[servicio][0] += 1
        total[servicio][1] += len(fuente)
    resto_deepl = cfg["deepl_limite_total"] - uso["deepl_total"]
    respaldo = servicio_de_respaldo(cfg)

    print(f"\nPendiente de traducir (textos únicos que aún no están en la caché):")
    if tiene_clave(cfg, "deepl_clave"):
        print(f"  DeepL:     {total['deepl'][0]:>7,} textos {total['deepl'][1]:>11,} caracteres  "
              f"(quedan {max(0, resto_deepl):,} de cuota)")
    nombres = {
        "gemini_dialogos": f"Gemini diálogos ({modelo_dialogos(cfg)})",
        "gemini": f"Gemini resto ({cfg['gemini_modelo']})",
        "microsoft": "Microsoft",
        "ollama": "Ollama",
    }
    for s, etiqueta in nombres.items():
        if total[s][0]:
            print(f"  {etiqueta}:\n    {total[s][0]:>7,} textos {total[s][1]:>11,} caracteres")
    if total["deepl"][1] > resto_deepl:
        destino = f"Gemini ({modelo_dialogos(cfg)})" if respaldo == "gemini" else respaldo.capitalize()
        print(f"\n  La cuota de DeepL no alcanza: los diálogos que sobren irán a {destino}.")
    if respaldo == "gemini":
        print(f"  El resto de textos irá a Gemini ({cfg['gemini_modelo']}).")
    if respaldo == "microsoft":
        resto_ms = cfg["microsoft_limite_mensual"] - uso["microsoft"].get(mes_actual(), 0)
        print(f"  Microsoft: te quedan {resto_ms:,} caracteres este mes.")
    if respaldo == "ollama":
        print("\n  Sin clave de Gemini ni de Microsoft: lo que no va a DeepL se traducirá con Ollama.")
    if uso["gemini"]:
        print(f"\n  Gemini usado: {sum(uso['gemini'].values()):,} caracteres en total.")
    print()


def comando_traducir(ruta_xml, cfg, simular, limite, solo_deepl=False, sin_dialogos=False):
    arbol, entradas = leer_xml(ruta_xml)
    cache = leer_json(ARCHIVO_CACHE, {})
    uso = leer_uso()
    terminos = leer_json(ARCHIVO_GLOSARIO, GLOSARIO_EJEMPLO).get("terminos", {})

    plan = planificar(entradas, cache, cfg, simular)
    if solo_deepl:
        plan = [(f, s) for f, s in plan if s == "deepl"]
        print("Modo --solo-deepl: solo diálogos y misiones; el resto queda en inglés por ahora.")
    if sin_dialogos:
        plan = [(f, s) for f, s in plan if s != "deepl"]
        print("Modo --sin-dialogos: solo objetos, menús y demás; los diálogos quedan para después.")
    if limite:
        plan = plan[:limite]
    print(f"\n{len(plan)} textos únicos por traducir.")

    problemas = []
    traducidos = 0
    detenido = None
    deepl_agotado = False
    respaldo = servicio_de_respaldo(cfg)

    try:
        for servicio in ORDEN_SERVICIOS:
            items = [f for f, s in plan if s == servicio]
            # Diálogos que no cupieron en DeepL: con Gemini van al modelo de diálogos;
            # con Microsoft u Ollama se suman a ese servicio.
            sobrantes = deepl_agotado and not simular and not solo_deepl
            if sobrantes and servicio == ("gemini_dialogos" if respaldo == "gemini" else respaldo):
                items += [f for f, s in plan if s == "deepl" and f not in cache]
            if not items:
                continue
            funcion, modo, max_textos, max_chars = SERVICIOS[servicio]
            preparados = []
            for fuente in items:
                partes, protegidos = dividir(fuente, terminos, saltos=(modo != "plano"))
                preparados.append((fuente, marcar(partes, modo), protegidos))
            if servicio == "gemini_dialogos":
                print(f"\n== GEMINI, diálogos y misiones ({modelo_dialogos(cfg)}): {len(preparados)} textos ==")
            elif servicio == "gemini":
                print(f"\n== GEMINI, resto de textos ({cfg['gemini_modelo']}): {len(preparados)} textos ==")
            else:
                print(f"\n== {servicio.upper()}: {len(preparados)} textos ==")

            for lote in lotes(preparados, max_textos, max_chars):
                n_chars = sum(len(x[1]) for x in lote)
                if servicio == "deepl" and uso["deepl_total"] + n_chars > cfg["deepl_limite_total"]:
                    deepl_agotado = True
                if servicio == "microsoft":
                    gastado = uso["microsoft"].get(mes_actual(), 0)
                    if gastado + n_chars > cfg["microsoft_limite_mensual"]:
                        detenido = ("Límite mensual de Microsoft alcanzado. Vuelve a ejecutar el mes que "
                                    "viene, o sube 'microsoft_limite_mensual' en config.json "
                                    "(cada millón extra cuesta unos 10 USD).")
                        break

                if not deepl_agotado or servicio != "deepl":
                    try:
                        resultados = funcion([x[1] for x in lote], cfg)
                    except CuotaAgotada:
                        deepl_agotado = True

                if servicio == "deepl" and deepl_agotado:
                    if solo_deepl:
                        print("   Cuota de DeepL agotada: el resto de diálogos queda en inglés por ahora.")
                    else:
                        print(f"   Cuota de DeepL agotada: el resto de diálogos irá a {respaldo}.")
                    break

                for (fuente, _, protegidos), crudo in zip(lote, resultados):
                    final = restaurar(crudo, protegidos, modo)
                    if final is None or not final.strip():
                        problemas.append((servicio, "variables rotas o respuesta vacía", fuente, crudo))
                        continue
                    motivo = motivo_sospecha(fuente, final) if servicio in SERVICIOS_IA else None
                    if motivo:
                        problemas.append((servicio, motivo, fuente, final))
                        continue
                    cache[fuente] = final
                    traducidos += 1
                if servicio == "deepl":
                    uso["deepl_total"] += n_chars
                elif servicio == "microsoft":
                    uso["microsoft"][mes_actual()] = uso["microsoft"].get(mes_actual(), 0) + n_chars
                elif servicio in ("gemini", "gemini_dialogos"):
                    uso["gemini"][hoy()] = uso["gemini"].get(hoy(), 0) + n_chars
                if not simular:
                    guardar_json(ARCHIVO_CACHE, cache)
                    guardar_json(ARCHIVO_USO, uso)
                print(f"   {traducidos} traducidos...")

            if detenido:
                break
    except KeyboardInterrupt:
        detenido = "Interrumpido con Ctrl+C. Lo traducido está guardado; vuelve a ejecutar para continuar."
    except ErrorFatal as e:
        detenido = f"{e}\nLo traducido hasta ahora está guardado; al volver a ejecutar, continúa."

    # Escribir el XML de salida
    escritas = 0
    for nodo, _, fuente in entradas:
        traduccion = cache.get(fuente)
        if traduccion is None:
            continue
        dest = nodo.find("Dest")
        if dest is None:
            dest = ET.SubElement(nodo, "Dest")
        dest.text = traduccion
        escritas += 1

    nombre = ruta_xml.stem
    nombre = nombre[:-3] if nombre.lower().endswith("_en") else nombre
    sufijo = "_SIMULADO" if simular else ""
    salida = ruta_xml.with_name(f"{nombre}_nl{sufijo}.xml")
    arbol.write(salida, encoding="utf-8", xml_declaration=True)
    # Nota: en modo --simular la caché no se guarda, para no mezclarla con traducciones reales.

    if problemas:
        ruta_prob = escribir_csv(ruta_xml.with_name(f"{nombre}_problemas.csv"),
                                 ["servicio", "motivo", "original", "respuesta_del_traductor"], problemas)

    print("\n" + "=" * 60)
    print(f"Textos traducidos en esta ejecución: {traducidos}")
    print(f"Líneas escritas en el XML:          {escritas} de {len(entradas)}")
    print(f"Archivo de salida:                  {salida.name}")
    if problemas:
        print(f"Textos con problemas:               {len(problemas)}  -> ver {ruta_prob.name}")
        print("  (quedan en inglés; al volver a ejecutar se reintentan)")
    if not simular:
        print(f"Uso DeepL total:                    {uso['deepl_total']:,} / {cfg['deepl_limite_total']:,}")
        if uso["gemini"]:
            print(f"Uso Gemini hoy:                     {uso['gemini'].get(hoy(), 0):,} caracteres")
        if tiene_microsoft(cfg):
            print(f"Uso Microsoft este mes:             {uso['microsoft'].get(mes_actual(), 0):,} / "
                  f"{cfg['microsoft_limite_mensual']:,}")
    if detenido:
        print("\n" + detenido)
    print("=" * 60 + "\n")


def comando_comparar(ruta_xml, cfg, n):
    """Traduce con Gemini textos que DeepL ya tradujo y guarda los dos lado a lado en un CSV."""
    if not tiene_gemini(cfg):
        raise ErrorFatal("Falta la clave de Gemini: pega 'gemini_clave' en config.json.")
    _, entradas = leer_xml(ruta_xml)
    cache = leer_json(ARCHIVO_CACHE, {})
    uso = leer_uso()
    terminos = leer_json(ARCHIVO_GLOSARIO, GLOSARIO_EJEMPLO).get("terminos", {})

    vistos, candidatos = set(), []
    for _, tipo, fuente in entradas:
        if tipo in cfg["deepl_tipos"] and fuente in cache and fuente not in vistos and len(fuente) >= 25:
            vistos.add(fuente)
            candidatos.append(fuente)
    if not candidatos:
        raise ErrorFatal("No hay diálogos traducidos por DeepL en la caché para comparar.")
    paso = max(1, len(candidatos) // n)
    muestra = candidatos[::paso][:n]

    funcion, modo, max_textos, max_chars = SERVICIOS["gemini_dialogos"]
    preparados = []
    for fuente in muestra:
        partes, protegidos = dividir(fuente, terminos, saltos=False)
        preparados.append((fuente, marcar(partes, modo), protegidos))

    print(f"\nTraduciendo {len(muestra)} diálogos con Gemini ({modelo_dialogos(cfg)}) para comparar...")
    filas = []
    for lote in lotes(preparados, max_textos, max_chars):
        resultados = funcion([x[1] for x in lote], cfg)
        for (fuente, _, protegidos), crudo in zip(lote, resultados):
            final = restaurar(crudo, protegidos, modo)
            filas.append((fuente, cache[fuente], final if final is not None else "[ERROR] " + crudo))
        n_chars = sum(len(x[1]) for x in lote)
        uso["gemini"][hoy()] = uso["gemini"].get(hoy(), 0) + n_chars
        guardar_json(ARCHIVO_USO, uso)

    ruta = escribir_csv(CARPETA / "comparacion_deepl_gemini.csv", ["ingles", "deepl", "gemini"], filas)
    errores = sum(1 for _, _, g in filas if g.startswith("[ERROR]"))
    print(f"\nListo: {len(filas)} comparaciones en {ruta.name} (ábrelo con Excel).")
    if errores:
        print(f"Gemini rompió variables en {errores} textos (marcados con [ERROR]).")
    print()


def comando_buscar(ruta_xml, frases):
    """Diagnóstico: dice en qué paso se quedó un texto que sigue en inglés dentro del juego."""
    _, entradas = leer_xml(ruta_xml)
    cache = leer_json(ARCHIVO_CACHE, {})
    exportados = set()
    ruta_trad = CARPETA / "traducciones_nl.txt"
    if ruta_trad.exists():
        with open(ruta_trad, encoding="utf-8-sig") as f:
            exportados = {linea.split("\t", 1)[0] for linea in f}
    campos = set()
    ruta_campos = CARPETA / "campos_nl.txt"
    if ruta_campos.exists():
        with open(ruta_campos, encoding="utf-8-sig") as f:
            campos = {linea.strip() for linea in f}
    patron_par = re.compile(r"([A-Z0-9_]{4})\W+([A-Z0-9_]{4})")

    for frase in frases:
        print("\n" + "=" * 70)
        print(f'Buscando: "{frase}"')
        encontrados = [(n, t, s) for n, t, s in entradas if frase.lower() in s.lower()]
        if not encontrados:
            print("  -> NO está en el XML de xTranslator.")
            print("     Este texto no sale de FalloutNV.esm (o xTranslator no lo exportó).")
            continue
        for nodo, tipo, fuente in encontrados[:5]:
            rec = (nodo.findtext("REC") or "").strip()
            edid = (nodo.findtext("EDID") or "").strip()
            m = patron_par.search(rec.upper())
            par = f"{m.group(1)}:{m.group(2)}" if m else "?"
            print(f"\n  Registro: {rec}   EDID: {edid}")
            print(f"  Inglés:   {fuente[:90]!r}")
            nl = cache.get(fuente)
            if nl is None:
                print("  -> NO traducido (no está en la caché).")
                continue
            print(f"  Holandés: {nl[:90]!r}")
            if clave_xedit(fuente) not in exportados:
                print("  -> Traducido, pero NO exportado a traducciones_nl.txt.")
            elif par not in campos:
                print(f"  -> Traducido y exportado, pero el campo {par} no está en campos_nl.txt.")
            else:
                print(f"  -> Traducido y exportado (campo {par}). Si sigue en inglés, falla el paso de FNVEdit.")
        if len(encontrados) > 5:
            print(f"\n  (y {len(encontrados) - 5} coincidencias más)")
    print()


def clave_xedit(texto):
    """Clave de búsqueda para FNVEdit: espacios, tabuladores y saltos de línea se reducen a un
    espacio y se quitan los de los extremos. Debe coincidir con Clave() de Traduccion_NL.pas."""
    return re.sub(r"[ \t\r\n]+", " ", texto).strip(" ")


PROMPT_GMST = """
Extra context for THIS request: these are user-interface strings of the game engine (menus, buttons,
HUD messages, Pip-Boy labels, confirmation dialogs). Use the usual Dutch terms of Dutch games and software
(e.g. Opslaan, Laden, Doorgaan, Instellingen, Afsluiten, Annuleren, Ja, Nee, Pakken).
Keep them as short as the English: screen space is very limited. Keep abbreviations as short abbreviations.
Keep the capitalization style (ALL CAPS stays ALL CAPS, Title Case may become normal Dutch capitalization)."""


def leer_texto(ruta):
    datos = ruta.read_bytes()
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return datos.decode("cp1252")


def gmst_tecnico(valor):
    """Valores de Game Settings que no son texto para el jugador (rutas, archivos, códigos)."""
    if not tiene_letras(valor) or "\\" in valor or "/" in valor:
        return True
    return re.search(r"\.(dds|nif|kf|wav|ogg|mp3|xml|txt|esp|esm|bsa|fnt|tex|psa|spt)\b", valor, re.I) is not None


def comando_gmst(ruta_txt, cfg, simular):
    """Traduce los Game Settings (textos del interfaz) exportados con Exportar_GMST.pas."""
    if not simular and not tiene_gemini(cfg):
        raise ErrorFatal("Falta la clave de Gemini en config.json.")
    entradas = []
    for linea in leer_texto(ruta_txt).splitlines():
        if "\t" not in linea:
            continue
        edid, valor = linea.split("\t", 1)
        valor = valor.replace("{{NL}}", "\n").replace("{{TAB}}", "\t")
        if valor.strip():
            entradas.append((edid.strip(), valor))
    if not entradas:
        raise ErrorFatal(f"{ruta_txt.name} está vacío. ¿Ejecutaste Exportar_GMST en FNVEdit?")

    cache = leer_json(ARCHIVO_CACHE, {})
    uso = leer_uso()
    terminos = leer_json(ARCHIVO_GLOSARIO, GLOSARIO_EJEMPLO).get("terminos", {})
    cfg_ui = {**cfg, "_prompt_extra": PROMPT_GMST}
    funcion, modo, max_textos, max_chars = SERVICIOS["simular" if simular else "gemini"]

    pendientes = list(dict.fromkeys(v for _, v in entradas if not gmst_tecnico(v) and v not in cache))
    print(f"\n{len(entradas)} Game Settings de texto; {len(pendientes)} por traducir "
          f"({'simulado' if simular else cfg['gemini_modelo']}).")
    preparados = []
    for fuente in pendientes:
        partes, protegidos = dividir(fuente, terminos, saltos=False)
        preparados.append((fuente, marcar(partes, modo), protegidos))

    problemas = []
    try:
        for lote in lotes(preparados, max_textos, max_chars):
            resultados = funcion([x[1] for x in lote], cfg_ui)
            for (fuente, _, protegidos), crudo in zip(lote, resultados):
                final = restaurar(crudo, protegidos, modo)
                motivo = None if final and final.strip() else "variables rotas o respuesta vacía"
                if not motivo:
                    motivo = motivo_sospecha(fuente, final)
                if motivo:
                    problemas.append((fuente, motivo))
                elif not simular:
                    cache[fuente] = final
            if not simular:
                n_chars = sum(len(x[1]) for x in lote)
                uso["gemini"][hoy()] = uso["gemini"].get(hoy(), 0) + n_chars
                guardar_json(ARCHIVO_CACHE, cache)
                guardar_json(ARCHIVO_USO, uso)
            print(f"   {len(cache)} en caché...")
    except ErrorFatal as e:
        print(f"\n{e}\nLo traducido está guardado; vuelve a ejecutar para continuar.")

    nombre = ruta_txt.stem
    nombre = nombre[:-3] if nombre.lower().endswith("_en") else nombre
    salida = ruta_txt.with_name(f"{nombre}_nl.txt")   # gmst_en -> gmst_nl, gmst_exe_en -> gmst_exe_nl
    n = 0
    with open(salida, "w", encoding="utf-8-sig", newline="\r\n") as f:
        for edid, valor in entradas:
            nl = cache.get(valor)
            if nl and nl != valor and not gmst_tecnico(valor):
                f.write(f"{edid}\t{escapar_xedit(nl)}\n")
                n += 1
    print(f"\nGame Settings traducidos: {n}  -> {salida}")
    if problemas:
        print(f"Con problemas (quedan en inglés): {len(problemas)}")
        for fuente, motivo in problemas[:10]:
            print(f"   {fuente!r}: {motivo}")
    print()


def comando_exe_gmst(ruta_exe):
    """Lee FalloutNV.exe (sin modificarlo) y extrae los Game Settings de texto que el juego
    lleva dentro con su valor en inglés (sYes, sTake, sNew...). Busca en el código el patrón
    con el que el juego los crea: push "valor" / push "nombre"."""
    import struct
    datos = ruta_exe.read_bytes()
    if datos[:2] != b"MZ":
        raise ErrorFatal(f"{ruta_exe.name} no es un ejecutable de Windows.")
    pe = struct.unpack_from("<I", datos, 0x3C)[0]
    if datos[pe:pe + 4] != b"PE\0\0":
        raise ErrorFatal(f"{ruta_exe.name} no es un ejecutable válido.")
    n_sec = struct.unpack_from("<H", datos, pe + 6)[0]
    tam_opt = struct.unpack_from("<H", datos, pe + 20)[0]
    opt = pe + 24
    if struct.unpack_from("<H", datos, opt)[0] != 0x10B:
        raise ErrorFatal("Se esperaba un ejecutable de 32 bits (FalloutNV.exe).")
    base = struct.unpack_from("<I", datos, opt + 28)[0]
    secciones = []
    for i in range(n_sec):
        off = opt + tam_opt + 40 * i
        vsize, va, rawsize, rawptr = struct.unpack_from("<IIII", datos, off + 8)
        secciones.append((va, max(vsize, rawsize), rawptr, rawsize))

    def va_a_offset(v):
        rva = v - base
        for va, tam, rawptr, rawsize in secciones:
            if va <= rva < va + tam and rva - va < rawsize:
                return rawptr + rva - va
        return None

    def cadena(v):
        off = va_a_offset(v)
        if off is None:
            return None
        fin = datos.find(b"\0", off, off + 1000)
        if fin < 0:
            return None
        try:
            texto = datos[off:fin].decode("cp1252")
        except UnicodeDecodeError:
            return None  # bytes que no son texto
        if any(ord(c) < 32 and c not in "\n\t\r" for c in texto):
            return None
        return texto

    es_nombre = re.compile(r"s[A-Z0-9][A-Za-z0-9_]{1,80}")
    encontrados = {}
    for m in re.finditer(rb"(?=\x68(.{4})\x68(.{4}))", datos, re.S):
        a = struct.unpack("<I", m.group(1))[0]
        b = struct.unpack("<I", m.group(2))[0]
        for v_valor, v_nombre in ((a, b), (b, a)):
            nombre = cadena(v_nombre)
            if not nombre or not es_nombre.fullmatch(nombre) or nombre in encontrados:
                continue
            valor = cadena(v_valor)
            if valor is not None and not es_nombre.fullmatch(valor):
                encontrados[nombre] = valor
                break

    utiles = {k: v for k, v in encontrados.items() if v.strip() and not gmst_tecnico(v)}
    print(f"\nGame Settings de texto encontrados en {ruta_exe.name}: {len(encontrados)}")
    print(f"Con texto para el jugador: {len(utiles)}")
    muestra = [k for k in ("sYes", "sNo", "sTake", "sTalk", "sWait", "sLoad", "sQuit") if k in utiles]
    for k in muestra:
        print(f"   {k} = {utiles[k]!r}")
    if len(utiles) < 100:
        raise ErrorFatal(
            "Encontré muy pocos. Probablemente el ejecutable de Steam está cifrado (protección DRM) "
            "y no se puede leer así. Avísame y usamos el plan B."
        )
    salida = CARPETA / "gmst_exe_en.txt"
    with open(salida, "w", encoding="utf-8-sig", newline="\r\n") as f:
        for k in sorted(utiles):
            f.write(f"{k}\t{escapar_xedit(utiles[k])}\n")
    print(f"\nGuardado en {salida.name}. Siguiente paso:")
    print(f"   python traducir_fnv.py gmst {salida.name}\n")


def escapar_xedit(texto):
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    return texto.replace("\n", "{{NL}}").replace("\t", "{{TAB}}")


def comando_exportar_xedit(rutas_xml):
    """Crea traducciones_nl.txt y campos_nl.txt (los leen esm_nl.py y Traduccion_NL.pas).
    Acepta varios XML (juego base + DLC): todo va a los mismos dos archivos, así que sirven
    para cualquiera de los .esm."""
    entradas = []
    for ruta in rutas_xml:
        _, de_este = leer_xml(ruta)
        print(f"  {ruta.name}: {len(de_este):,} líneas")
        entradas += de_este
    cache = leer_json(ARCHIVO_CACHE, {})
    patron_par = re.compile(r"([A-Z0-9_]{4})\W+([A-Z0-9_]{4})")
    traducciones, campos = {}, set()
    for nodo, tipo, fuente in entradas:
        destino = cache.get(fuente)
        if not destino or not destino.strip() or destino == fuente or tipo == "TES4":
            continue
        rec = nodo.find("REC")
        m = patron_par.search((rec.text or "").upper()) if rec is not None else None
        if not m:
            continue
        campos.add(f"{m.group(1)}:{m.group(2)}")
        traducciones[clave_xedit(fuente)] = escapar_xedit(destino.strip(" \t\r\n"))

    if not traducciones:
        raise ErrorFatal("No hay traducciones en la caché para este XML. ¿Ya ejecutaste 'traducir'?")

    ruta_trad = CARPETA / "traducciones_nl.txt"
    ruta_campos = CARPETA / "campos_nl.txt"
    with open(ruta_trad, "w", encoding="utf-8-sig", newline="\r\n") as f:
        for en, nl in traducciones.items():
            f.write(f"{en}\t{nl}\n")
    with open(ruta_campos, "w", encoding="utf-8-sig", newline="\r\n") as f:
        for par in sorted(campos):
            f.write(par + "\n")

    print(f"\nTextos traducidos exportados: {len(traducciones):,}")
    print(f"Tipos de campo con texto:     {len(campos)}")
    print(f"\nCopia estos dos archivos a la carpeta 'Edit Scripts' de FNVEdit:")
    print(f"  {ruta_trad.name}")
    print(f"  {ruta_campos.name}\n")


def main():
    p = argparse.ArgumentParser(description="Traduce al holandés el XML exportado con xTranslator.")
    p.add_argument("comando", choices=["contar", "traducir", "comparar", "exportar-xedit", "buscar", "gmst", "exe-gmst"])
    p.add_argument("xml", type=Path, help="Archivo XML exportado con xTranslator")
    p.add_argument("frases", nargs="*", help="Con 'buscar': textos en inglés a diagnosticar, entre comillas")
    p.add_argument("--simular", action="store_true", help="No usa ninguna API; solo prueba el proceso")
    p.add_argument("--limite", type=int, default=0, help="Traducir (o comparar) solo N textos")
    p.add_argument("--solo-deepl", action="store_true",
                   help="Traduce solo diálogos y misiones con DeepL; no usa otros servicios")
    p.add_argument("--sin-dialogos", action="store_true",
                   help="Traduce solo objetos, menús y demás textos; deja los diálogos para después")
    args = p.parse_args()
    if args.solo_deepl and args.sin_dialogos:
        sys.exit("--solo-deepl y --sin-dialogos no se pueden usar juntos.")

    creados = preparar_archivos()
    if creados:
        print(f"He creado {', '.join(creados)} en {CARPETA}.")
    cfg = {**CONFIG_EJEMPLO, **leer_json(ARCHIVO_CONFIG, {})}

    if not args.xml.exists():
        sys.exit(f"No encuentro el archivo {args.xml}")

    necesita_claves = args.comando == "traducir" and not args.simular
    if necesita_claves and args.solo_deepl and not tiene_clave(cfg, "deepl_clave"):
        sys.exit("--solo-deepl necesita 'deepl_clave' en config.json.")
    if necesita_claves and not tiene_clave(cfg, "deepl_clave") and not tiene_gemini(cfg):
        sys.exit("Pega tu clave de Gemini ('gemini_clave') en config.json (ábrelo con el Bloc de notas).")
    if necesita_claves and not tiene_clave(cfg, "deepl_clave"):
        print(f"Sin DeepL: diálogos y misiones con Gemini ({modelo_dialogos(cfg)}), "
              f"el resto con Gemini ({cfg['gemini_modelo']}).")
    if necesita_claves and not args.solo_deepl:
        print(f"Lo que no vaya a DeepL se traducirá con: {servicio_de_respaldo(cfg).capitalize()}")
        if servicio_de_respaldo(cfg) == "ollama":
            print("(Ollama debe estar abierto. Si no lo tienes, pega 'gemini_clave' en config.json.)")

    try:
        if args.comando == "contar":
            comando_contar(args.xml, cfg)
        elif args.comando == "exe-gmst":
            comando_exe_gmst(args.xml)
        elif args.comando == "gmst":
            comando_gmst(args.xml, cfg, args.simular)
        elif args.comando == "buscar":
            comando_buscar(args.xml, args.frases)
        elif args.comando == "exportar-xedit":
            extra = [Path(f) for f in args.frases]
            for f in extra:
                if not f.exists():
                    sys.exit(f"No encuentro el archivo {f}")
            comando_exportar_xedit([args.xml] + extra)
        elif args.comando == "comparar":
            comando_comparar(args.xml, cfg, args.limite or 30)
        else:
            comando_traducir(args.xml, cfg, args.simular, args.limite, args.solo_deepl, args.sin_dialogos)
    except ErrorFatal as e:
        sys.exit(f"\nError: {e}")


if __name__ == "__main__":
    main()