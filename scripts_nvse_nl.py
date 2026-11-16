#!/usr/bin/env python3
"""
scripts_nvse_nl.py
Traduce al holandés textos que salen en pantalla y que NO están en los plugins:
  1) Scripts de xNVSE (nvse\\plugins\\scripts\\*.txt): descripciones de perks/rasgos
     (SetFormDescription), nombres (SetName...) y mensajes (MessageEx, MessageBoxEx...).
     Ejemplo: PerkOut reescribe al cargar la partida Hamster, Logan's Loophole, Strong Back...
  2) B42 Descriptions / Pip-Info (Config\\B42Descriptions\\<plugin>\\*.ini): las descripciones
     extra de objetos del Pip-Boy (Objeto=texto). Solo las carpetas de plugins activos.

No modifica el modlist. Escribe copias traducidas en el mod de MO2 "[NL] Wild Card Nederlands"
con la misma ruta. Solo cambia el texto; nombres de formularios, variables, claves e INI de
configuración no se tocan.

Va en la carpeta FNV_NL, junto a traducir_fnv.py y cache_traducciones.json.

Uso (PowerShell, desde FNV_NL, con MO2 cerrado):
  python scripts_nvse_nl.py contar                     (gratis: qué scripts y cuántos textos)
  python scripts_nvse_nl.py xml                        (crea ScriptsNVSE_en_de.xml)
  python traducir_fnv.py traducir ScriptsNVSE_en_de.xml   (lo que ya está en caché es gratis)
  python scripts_nvse_nl.py construir                  (escribe las copias en el mod [NL])

Opciones:
  --mo2 RUTA        carpeta del modlist (por defecto F:\\Mods\\FWC)
  --perfil NOMBRE   perfil de MO2 (por defecto el seleccionado en MO2)
  --todos           B42: traducir también carpetas de plugins que no están activos (p. ej. TTW)

Tras actualizar Wild Card con Wabbajack: repetir xml -> traducir -> construir.
"""

import csv
import datetime
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
MO2_POR_DEFECTO = r"F:\Mods\FWC"
MOD_NL = "[NL] Wild Card Nederlands"
ARCHIVO_XML = "ScriptsNVSE_en_de.xml"
ARCHIVO_PROBLEMAS = "ScriptsNVSE_problemas.csv"
CARPETA_SCRIPTS = ("nvse", "plugins", "scripts")
CARPETA_B42 = ("config", "b42descriptions")

# Órdenes cuyo texto entre comillas sale en pantalla -> campo para el XML (solo orienta al traductor).
ORDENES = {
    "setformdescription": "PERK:DESC",
    "setdescription": "PERK:DESC",
    "setdescriptionjip": "PERK:DESC",
    "setdescriptionalt": "PERK:DESC",
    "setname": "MISC:FULL",
    "setnameex": "MISC:FULL",
    "setnamealt": "MISC:FULL",
    "messageex": "MESG:DESC",
    "messageboxex": "MESG:DESC",
    "messageboxexalt": "MESG:DESC",
    "messageboxalt": "MESG:DESC",
}
TIPO_B42 = "BOOK:DESC"
PATRON_ORDEN = re.compile(r"(?i)(?<![A-Za-z0-9_])(" + "|".join(sorted(ORDENES, key=len, reverse=True))
                          + r")(?![A-Za-z0-9_])")
PATRON_CADENA = re.compile(r'"([^"\r\n]*)"')
# Códigos de formato de xNVSE (%r salto de línea, %q comillas, %g/%.0f números, %n nombre, %%...)
PATRON_FORMATO = re.compile(r"%[-+ 0#]*\d*(?:\.\d+)?[A-Za-z%]")
CAMBIOS_CP1252 = {"\u2018": "'", "\u2019": "'", "\u201c": "'", "\u201d": "'", "\u201e": "'", '"': "'",
                  "\u2026": "...", "\u2013": "-", "\u2014": "-", "\u00a0": " "}


class ErrorFatal(Exception):
    pass


# ---------------------------------------------------------------- utilidades

def leer_texto(ruta):
    datos = Path(ruta).read_bytes()
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return datos.decode("cp1252")


def clave(texto):
    """Igual que clave_xedit() de traducir_fnv.py."""
    return re.sub(r"[ \t\r\n]+", " ", texto).strip(" ")


def tiene_letras(texto):
    return re.search(r"[A-Za-z]{2}", texto) is not None


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


# ---------------------------------------------------------------- MO2

def valor_ini(txt, nombre):
    m = re.search(r"^\s*" + re.escape(nombre) + r"\s*=\s*(.*)$", txt, re.M)
    if not m:
        return None
    v = m.group(1).strip()
    if v.startswith("@ByteArray(") and v.endswith(")"):
        v = v[len("@ByteArray("):-1]
    return v.replace("\\\\", "\\").replace("/", "\\")


class Modlist:
    def __init__(self, raiz, perfil=None):
        self.raiz = Path(raiz)
        ini = self.raiz / "ModOrganizer.ini"
        if not ini.exists():
            raise ErrorFatal(f"No encuentro {ini}. Usa --mo2 con la carpeta del modlist.")
        txt = leer_texto(ini)
        juego = valor_ini(txt, "gamePath")
        self.data = Path(juego) / "Data" if juego else None
        mods = valor_ini(txt, "mod_directory")
        self.mods = Path(mods.replace("%BASE_DIR%", str(self.raiz))) if mods else self.raiz / "mods"
        self.overwrite = self.raiz / "overwrite"
        self.perfil = perfil or valor_ini(txt, "selected_profile")
        dir_perfil = self.raiz / "profiles" / (self.perfil or "")
        ruta = dir_perfil / "modlist.txt"
        if not self.perfil or not ruta.exists():
            raise ErrorFatal(f"No encuentro el perfil '{self.perfil}'. Usa --perfil \"nombre\".")
        # modlist.txt: la primera línea es la de MÁS prioridad.
        self.activos = [l[1:] for l in leer_texto(ruta).splitlines()
                        if l.startswith("+") and not l.endswith("_separator") and l[1:] != MOD_NL]
        self.activo_nl = any(l.strip() == "+" + MOD_NL for l in leer_texto(ruta).splitlines())
        ruta_plugins = dir_perfil / "plugins.txt"
        # FalloutNV.esm y los DLC se cargan siempre, aunque plugins.txt no los nombre.
        self.plugins = {"falloutnv", "deadmoney", "honesthearts", "oldworldblues", "lonesomeroad",
                        "gunrunnersarsenal", "classicpack", "mercenarypack", "tribalpack", "caravanpack"}
        if ruta_plugins.exists():
            for l in leer_texto(ruta_plugins).splitlines():
                l = l.strip().lstrip("*")
                if l and not l.startswith("#"):
                    self.plugins.add(Path(l).stem.lower())

    def carpetas(self):
        """(nombre, carpeta) de mayor a menor prioridad: overwrite > mods > juego."""
        lista = [("overwrite", self.overwrite)] + [(m, self.mods / m) for m in self.activos]
        if self.data:
            lista.append(("juego (Data)", self.data))
        return lista

    def ganadores(self, partes, extension):
        """{ruta relativa en minúsculas: (ruta relativa, archivo, mod)} con el archivo que ve el juego."""
        ganadores = {}
        for nombre, carpeta in self.carpetas():
            base = subcarpeta(carpeta, partes)
            if base is None:
                continue
            for f in base.rglob("*"):
                if f.is_file() and f.suffix.lower() == extension:
                    rel = f.relative_to(carpeta)
                    ganadores.setdefault(str(rel).lower().replace("/", "\\"), (rel, f, nombre))
        return ganadores


def subcarpeta(carpeta, partes):
    """carpeta/partes sin distinguir mayúsculas (Config vs config, NVSE vs nvse)."""
    actual = carpeta
    for parte in partes:
        if not actual.is_dir():
            return None
        siguiente = next((d for d in actual.iterdir() if d.is_dir() and d.name.lower() == parte), None)
        if siguiente is None:
            return None
        actual = siguiente
    return actual


# ---------------------------------------------------------------- scripts

class Script:
    """Script de xNVSE o INI de B42. Conserva bytes, codificación y saltos de línea."""

    def __init__(self, ruta, tipo="script"):
        self.tipo = tipo
        # El juego muestra el texto en cp1252. Se lee byte a byte (surrogateescape) para que lo que
        # no se traduce quede idéntico aunque el archivo tenga BOM o restos de UTF-8, y el texto
        # nuevo se escribe en cp1252.
        self.texto = ruta.read_bytes().decode("cp1252", errors="surrogateescape")
        self.lineas = self.texto.splitlines(keepends=True)

    def textos(self):
        """[(n.º de línea, inicio, fin, orden, texto)] de las cadenas que salen en pantalla."""
        if self.tipo == "b42":
            return self.textos_ini()
        salida = []
        for i, linea in enumerate(self.lineas):
            codigo = linea.split(";", 1)[0] if '"' not in linea.split(";", 1)[0] else linea
            m = PATRON_ORDEN.search(codigo)
            if not m:
                continue
            for c in PATRON_CADENA.finditer(linea, m.end()):
                if tiene_letras(c.group(1)):
                    salida.append((i, c.start(1), c.end(1), m.group(1).lower(), c.group(1)))
        return salida

    def textos_ini(self):
        salida = []
        for i, linea in enumerate(self.lineas):
            cuerpo = linea.rstrip("\r\n")
            if not cuerpo.strip() or cuerpo.lstrip()[:1] in (";", "#", "[") or "=" not in cuerpo:
                continue
            ini = cuerpo.index("=") + 1
            valor = cuerpo[ini:]
            limpio = valor.strip()
            if not tiene_letras(limpio):
                continue
            ini += len(valor) - len(valor.lstrip())
            salida.append((i, ini, ini + len(limpio), "b42", limpio))
        return salida

    def otras_frases(self):
        if self.tipo == "b42":
            return 0
        """Cadenas entre comillas fuera de esas órdenes que parecen frases (solo para avisar)."""
        n = 0
        for linea in self.lineas:
            if PATRON_ORDEN.search(linea):
                continue
            for c in PATRON_CADENA.finditer(linea):
                if len(re.findall(r"[A-Za-z]{2,}", c.group(1))) >= 4 and " " in c.group(1):
                    n += 1
        return n

    def guardar(self, destino, lineas):
        destino.parent.mkdir(parents=True, exist_ok=True)
        datos = "".join(lineas).encode("cp1252", errors="surrogateescape")
        destino.write_bytes(datos)


def para_traducir(texto):
    """%q es una comilla doble para xNVSE/B42: el traductor ve comillas normales."""
    return texto.replace("%q", '"')


def adaptar(fuente, nl):
    """Prepara la traducción para meterla en un script o INI. Devuelve (texto, problema)."""
    if not nl or not nl.strip():
        return None, "sin traducción"
    nl = nl.strip()
    if "%q" in fuente:                       # comillas de la traducción -> %q, como el original
        for c in ("\u201c", "\u201d", "\u201e"):
            nl = nl.replace(c, '"')
        nl = nl.replace('"', "%q")
    if "%r" not in fuente:
        nl = re.sub(r"\s*\r?\n\s*", " ", nl)
    elif "\n" in nl:
        nl = re.sub(r"\r?\n", "%r", nl)
    for a, b in CAMBIOS_CP1252.items():
        nl = nl.replace(a, b)
    codigos = lambda t: Counter(c for c in PATRON_FORMATO.findall(t) if c != "%q")
    if codigos(fuente) != codigos(nl):
        return None, "códigos % distintos (%r, %g, %n...)"
    if fuente.count("|") != nl.count("|"):
        return None, "número de botones | distinto"
    try:
        nl.encode("cp1252")
    except UnicodeEncodeError:
        return None, "caracteres que el juego no muestra"
    return nl, None


# ---------------------------------------------------------------- traducciones

def leer_traducciones():
    """Texto inglés -> holandés: caché de traducir_fnv.py + traducciones exportadas."""
    exactas, por_clave = {}, {}
    ruta = CARPETA / "cache_traducciones.json"
    if ruta.exists():
        with open(ruta, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if isinstance(v, str) and v.strip() and v != k:
                    exactas[k] = v
                    por_clave.setdefault(clave(k), v)
    for txt in (CARPETA / "WILDCARD" / "traducciones_nl.txt", CARPETA / "traducciones_nl.txt"):
        if txt.exists():
            for linea in leer_texto(txt).splitlines():
                if "\t" in linea:
                    en, nl = linea.split("\t", 1)
                    nl = nl.replace("{{NL}}", "\n").replace("{{TAB}}", "\t")
                    por_clave.setdefault(clave(en), nl)
    return lambda t: exactas.get(t) or por_clave.get(clave(t))


def recoger(ml, todos=False):
    print(f"\nPerfil: {ml.perfil}")
    if not ml.activo_nl:
        print(f"  AVISO: \"{MOD_NL}\" no está activo en este perfil.")
    resultado = []
    for rel_min, (rel, archivo, mod) in sorted(ml.ganadores(CARPETA_SCRIPTS, ".txt").items()):
        s = Script(archivo)
        resultado.append((rel, archivo, mod, s, s.textos()))
    saltadas = set()
    for rel_min, (rel, archivo, mod) in sorted(ml.ganadores(CARPETA_B42, ".ini").items()):
        partes = rel_min.split("\\")
        plugin = partes[2] if len(partes) > 3 else ""
        if plugin and ml.plugins and plugin not in ml.plugins and not todos:
            saltadas.add(rel.parts[2])
            continue
        s = Script(archivo, "b42")
        resultado.append((rel, archivo, mod, s, s.textos()))
    if saltadas:
        print(f"  B42: carpetas de plugins no activos (no se traducen; --todos para incluirlas): "
              f"{', '.join(sorted(saltadas))}")
    return resultado


# ---------------------------------------------------------------- comandos

def comando_contar(ml, todos):
    datos = recoger(ml, todos)
    buscar = leer_traducciones()
    total = nuevos = car = otras = 0
    vistos = set()
    print(f"\n{'Archivo':<38} {'Mod':<34} {'textos':>6} {'nuevos':>6}")
    print("-" * 88)
    for rel, archivo, mod, s, textos in datos:
        n_nuevos = 0
        for _, _, _, _, t in textos:
            t = para_traducir(t)
            if not buscar(t) and t not in vistos:
                vistos.add(t)
                n_nuevos += 1
                car += len(t)
        otras += s.otras_frases()
        if textos:
            nombre = rel.name if s.tipo == "script" else f"B42 {rel.parts[2]}\\{rel.name}"
            print(f"{nombre[:38]:<38} {mod[:34]:<34} {len(textos):>6} {n_nuevos:>6}")
        total += len(textos)
        nuevos += n_nuevos
    print("-" * 88)
    print(f"Archivos (scripts + INI de B42):   {len(datos)}")
    print(f"Textos en pantalla encontrados:    {total}")
    print(f"Sin traducir todavía:              {nuevos} ({car:,} caracteres, ~{car / 1e6 * 4:.2f} USD)")
    if otras:
        print(f"\n(Otras {otras} cadenas entre comillas parecen frases pero no van en órdenes de texto\n"
              f" conocidas; no se tocan. Si ves algún texto en inglés que venga de un script, avísame.)")
    print("\nSiguiente paso: python scripts_nvse_nl.py xml\n")


def comando_xml(ml, todos):
    datos = recoger(ml, todos)
    raiz = ET.Element("SSTXMLRessources")
    params = ET.SubElement(raiz, "Params")
    for k, v in (("Addon", "ScriptsNVSE"), ("Source", "en"), ("Dest", "de"), ("Version", "2")):
        ET.SubElement(params, k).text = v
    contenido = ET.SubElement(raiz, "Content")
    vistos, n = set(), 0
    for rel, archivo, mod, s, textos in datos:
        for _, _, _, orden, t in textos:
            t = para_traducir(t)
            if t in vistos:
                continue
            vistos.add(t)
            nodo = ET.SubElement(contenido, "String", List="0", sID=f"{n:06X}")
            ET.SubElement(nodo, "EDID").text = rel.stem if s.tipo == "script" else "B42_" + rel.parts[2]
            tipo = ORDENES.get(orden, TIPO_B42)
            ET.SubElement(nodo, "REC", id=tipo[:4], idx="1").text = tipo
            ET.SubElement(nodo, "Source").text = t
            ET.SubElement(nodo, "Dest").text = t
            n += 1
    if not n:
        raise ErrorFatal("No encontré textos de pantalla en los scripts de xNVSE ni en B42.")
    destino = CARPETA / ARCHIVO_XML
    ET.ElementTree(raiz).write(destino, encoding="utf-8", xml_declaration=True)
    print(f"\nTextos distintos: {n}\nArchivo creado:   {destino}")
    print("\nSiguientes pasos:")
    print(f"   python traducir_fnv.py contar   {ARCHIVO_XML}")
    print(f"   python traducir_fnv.py traducir {ARCHIVO_XML}")
    print("   python scripts_nvse_nl.py construir\n")


def comando_construir(ml, todos):
    datos = recoger(ml, todos)
    buscar = leer_traducciones()
    salida_mod = ml.mods / MOD_NL
    print(f"Mod de salida: {salida_mod}\n")
    problemas = []
    n_archivos = n_textos = n_ingles = 0
    for rel, archivo, mod, s, textos in datos:
        destino = salida_mod / rel
        lineas = list(s.lineas)
        cambios = 0
        # De derecha a izquierda para que las posiciones sigan valiendo en la misma línea.
        for i, ini, fin, orden, t in sorted(textos, key=lambda x: (x[0], -x[1])):
            encontrada = buscar(para_traducir(t))
            nl, problema = adaptar(t, encontrada)
            if problema:
                problemas.append((str(rel), mod, problema, t, encontrada or ""))
                n_ingles += 1
                continue
            if nl != t:
                lineas[i] = lineas[i][:ini] + nl + lineas[i][fin:]
                cambios += 1
        if cambios:
            s.guardar(destino, lineas)
            n_archivos += 1
            n_textos += cambios
            print(f"  {rel}  ({mod}): {cambios} textos")
        elif destino.exists():
            destino.unlink()          # copia de una versión anterior que ya no hace falta
    if problemas:
        ruta = escribir_csv(CARPETA / ARCHIVO_PROBLEMAS,
                            ["script", "mod", "motivo", "ingles", "traduccion"], problemas)
    print("=" * 60)
    print(f"Archivos traducidos: {n_archivos}")
    print(f"Textos traducidos:   {n_textos}")
    if problemas:
        print(f"Quedan en inglés:    {n_ingles}  -> ver {ruta.name}")
        print("  (\"sin traducción\": ejecuta antes traducir_fnv.py traducir " + ARCHIVO_XML + ")")
    print("=" * 60)
    print(f"En MO2: F5. \"{MOD_NL}\" debe estar activo y por encima de los demás mods.\n")


def main():
    args = sys.argv[1:]
    opciones = {}
    todos = "--todos" in args
    args = [a for a in args if a != "--todos"]
    for nombre in ("mo2", "perfil"):
        bandera = "--" + nombre
        if bandera in args:
            i = args.index(bandera)
            if i + 1 >= len(args):
                raise ErrorFatal(f"Falta el valor de {bandera}")
            opciones[nombre] = args[i + 1]
            del args[i:i + 2]
    if not args or args[0] not in ("contar", "xml", "construir"):
        print(__doc__)
        return
    ml = Modlist(opciones.get("mo2") or MO2_POR_DEFECTO, opciones.get("perfil"))
    {"contar": comando_contar, "xml": comando_xml, "construir": comando_construir}[args[0]](ml, todos)


if __name__ == "__main__":
    try:
        main()
    except ErrorFatal as e:
        sys.exit(f"\nError: {e}")
