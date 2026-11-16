#!/usr/bin/env python3
"""
buscar_texto.py
Busca un texto en TODO lo que ve el juego en un modlist de Mod Organizer 2:
  - archivos sueltos de texto (xml, txt, ini, json...) de los mods activos, overwrite y Data
  - archivos de texto y menús DENTRO de los .bsa
  - plugins .esp/.esm/.esl, también dentro de los registros comprimidos (dice tipo de registro,
    EditorID y campo)
  - plugins DLL de NVSE (texto ASCII y UTF-16)
No modifica nada.

Uso (PowerShell, desde FNV_NL, con MO2 cerrado):
  python buscar_texto.py "Ghoul:"
  python buscar_texto.py "Ghoul:" "otro texto" --mo2 F:\\Mods\\FWC --perfil "FNV Wild Card - Casual - NVR Mode"
  python buscar_texto.py "Ghoul:" --sin-bsa        (más rápido: no mira dentro de los .bsa)

No distingue mayúsculas. El resultado también se guarda en buscar_texto_resultado.txt.
"""

import re
import struct
import sys
import zlib
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
MO2_POR_DEFECTO = r"F:\Mods\FWC"
EXT_TEXTO = {".xml", ".txt", ".ini", ".json", ".csv", ".lst", ".cfg", ".toml", ".yaml", ".xsl", ".psc"}
EXT_PLUGIN = {".esm", ".esp", ".esl"}
EXT_DLL = {".dll"}
CABECERA = 24
COMPRIMIDO = 0x00040000


class ErrorFatal(Exception):
    pass


def leer_texto(ruta):
    datos = Path(ruta).read_bytes()
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return datos.decode("cp1252", errors="replace")


# ---------------------------------------------------------------- MO2

def valor_ini(txt, nombre):
    m = re.search(r"^\s*" + re.escape(nombre) + r"\s*=\s*(.*)$", txt, re.M)
    if not m:
        return None
    v = m.group(1).strip()
    if v.startswith("@ByteArray(") and v.endswith(")"):
        v = v[len("@ByteArray("):-1]
    return v.replace("\\\\", "\\").replace("/", "\\")


def carpetas_modlist(raiz, perfil):
    raiz = Path(raiz)
    ini = raiz / "ModOrganizer.ini"
    if not ini.exists():
        raise ErrorFatal(f"No encuentro {ini}. Usa --mo2 con la carpeta del modlist.")
    txt = leer_texto(ini)
    perfil = perfil or valor_ini(txt, "selected_profile")
    mods = valor_ini(txt, "mod_directory")
    mods = Path(mods.replace("%BASE_DIR%", str(raiz))) if mods else raiz / "mods"
    ruta = raiz / "profiles" / (perfil or "") / "modlist.txt"
    if not ruta.exists():
        raise ErrorFatal(f"No encuentro el perfil '{perfil}'. Usa --perfil \"nombre\".")
    activos = [l[1:] for l in leer_texto(ruta).splitlines()
               if l.startswith("+") and not l.endswith("_separator")]
    lista = [("overwrite", raiz / "overwrite")] + [(m, mods / m) for m in activos]
    juego = valor_ini(txt, "gamePath")
    if juego:
        lista.append(("juego (Data)", Path(juego) / "Data"))
    return perfil, lista


# ---------------------------------------------------------------- BSA (Fallout 3 / New Vegas, v104)

class LectorBSA:
    def __init__(self, ruta):
        self.ruta = Path(ruta)
        with open(self.ruta, "rb") as f:
            cab = f.read(36)
            if len(cab) < 36 or cab[:4] != b"BSA\x00":
                raise ErrorFatal("no es un BSA")
            (version, off_carpetas, self.flags, n_carpetas, n_archivos,
             _, tam_nombres, _) = struct.unpack_from("<8I", cab, 4)
            if version not in (103, 104):
                raise ErrorFatal(f"versión de BSA {version} no soportada")
            f.seek(off_carpetas)
            carpetas = [struct.unpack("<QII", f.read(16)) for _ in range(n_carpetas)]
            registros = []
            for _, cuenta, _ in carpetas:
                nombre = ""
                if self.flags & 1:
                    n = f.read(1)[0]
                    nombre = f.read(n).rstrip(b"\x00").decode("cp1252", errors="replace")
                for _ in range(cuenta):
                    _, tam, off = struct.unpack("<QII", f.read(16))
                    registros.append((nombre, tam, off))
            nombres = f.read(tam_nombres).split(b"\x00") if self.flags & 2 else []
        self.archivos = {}
        for i, (carpeta, tam, off) in enumerate(registros):
            archivo = nombres[i].decode("cp1252", errors="replace") if i < len(nombres) else f"#{i}"
            self.archivos[(carpeta + "\\" + archivo).lower()] = (tam, off)

    def extraer(self, interna):
        tam, off = self.archivos[interna]
        comprimido = bool(self.flags & 4) != bool(tam & 0x40000000)
        tam &= 0x3FFFFFFF
        with open(self.ruta, "rb") as f:
            f.seek(off)
            datos = f.read(tam)
        if self.flags & 0x100:                 # nombre incrustado delante de los datos
            n = datos[0]
            datos = datos[1 + n:]
        if comprimido:
            datos = zlib.decompress(datos[4:])
        return datos


# ---------------------------------------------------------------- plugins

def subregistros(datos):
    p, grande = 0, None
    while p + 6 <= len(datos):
        sig = bytes(datos[p:p + 4])
        tam = struct.unpack_from("<H", datos, p + 4)[0]
        p += 6
        if grande is not None:
            tam, grande = grande, None
        if sig == b"XXXX":
            grande = struct.unpack_from("<I", datos, p)[0]
            p += tam
            continue
        yield sig, bytes(datos[p:p + tam])
        p += tam


def buscar_en_plugin(ruta, agujas):
    """[(texto, registro, EditorID, campo, fragmento)]"""
    buf = Path(ruta).read_bytes()
    if buf[:4] != b"TES4":
        return []
    salida = []

    def recorrer(p, fin):
        while p + CABECERA <= fin:
            sig = buf[p:p + 4]
            tam = struct.unpack_from("<I", buf, p + 4)[0]
            if sig == b"GRUP":
                recorrer(p + CABECERA, p + tam)
                p += tam
                continue
            flags = struct.unpack_from("<I", buf, p + 8)[0]
            cuerpo = buf[p + CABECERA:p + CABECERA + tam]
            if flags & COMPRIMIDO:
                try:
                    datos = zlib.decompress(cuerpo[4:])
                except zlib.error:
                    datos = b""
            else:
                datos = cuerpo
            bajo_d = datos.lower()
            if any(a in bajo_d for _, a in agujas):
                edid = ""
                for s, d in subregistros(datos):
                    if s == b"EDID":
                        edid = d.rstrip(b"\x00").decode("cp1252", errors="replace")
                for s, d in subregistros(datos):
                    for texto, a in agujas:
                        i = d.lower().find(a)
                        if i >= 0:
                            frag = d[max(0, i - 60):i + len(a) + 80].replace(b"\x00", b" ")
                            salida.append((texto, sig.decode("latin-1"), edid, s.decode("latin-1"),
                                           frag.decode("cp1252", errors="replace")))
            p += CABECERA + tam

    tam_tes4 = struct.unpack_from("<I", buf, 4)[0]
    recorrer(CABECERA + tam_tes4, len(buf))
    return salida


def fragmento(datos, i, largo):
    return datos[max(0, i - 60):i + largo + 80].decode("cp1252", errors="replace").replace("\r", " ").replace("\n", " ")


# ---------------------------------------------------------------- búsqueda

def main():
    args = sys.argv[1:]
    opciones = {}
    for nombre in ("mo2", "perfil"):
        b = "--" + nombre
        if b in args:
            i = args.index(b)
            opciones[nombre] = args[i + 1]
            del args[i:i + 2]
    sin_bsa = "--sin-bsa" in args
    args = [a for a in args if a != "--sin-bsa"]
    if not args:
        print(__doc__)
        return
    agujas = [(t, t.lower().encode("cp1252", errors="ignore")) for t in args]
    agujas16 = [(t, t.lower().encode("utf-16-le")) for t in args]
    perfil, carpetas = carpetas_modlist(opciones.get("mo2") or MO2_POR_DEFECTO, opciones.get("perfil"))
    print(f"\nPerfil: {perfil}\nBuscando: {', '.join(repr(t) for t in args)}\n")

    lineas = []

    def anotar(texto):
        print(texto)
        lineas.append(texto)

    n_archivos = n_bsa = n_plugins = 0
    for i, (mod, carpeta) in enumerate(carpetas, 1):
        if not carpeta.is_dir():
            continue
        if i % 100 == 0:
            print(f"  ... {i} de {len(carpetas)} carpetas revisadas", flush=True)
        for f in carpeta.rglob("*"):
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            rel = f.relative_to(carpeta)
            try:
                if ext in EXT_TEXTO and f.name.lower() != "meta.ini":
                    n_archivos += 1
                    datos = f.read_bytes()
                    bajo = datos.lower()
                    for texto, a in agujas:
                        j = bajo.find(a)
                        if j >= 0:
                            anotar(f"[SUELTO] {mod} :: {rel}\n          ...{fragmento(datos, j, len(a))}...")
                elif ext in EXT_PLUGIN:
                    n_plugins += 1
                    for texto, tipo, edid, campo, frag in buscar_en_plugin(f, agujas):
                        anotar(f"[PLUGIN] {mod} :: {rel}  registro {tipo} '{edid}' campo {campo}\n"
                               f"          ...{frag}...")
                elif ext in EXT_DLL:
                    datos = f.read_bytes().lower()
                    for (texto, a), (_, a16) in zip(agujas, agujas16):
                        if a in datos or a16 in datos:
                            anotar(f"[DLL]    {mod} :: {rel}  (contiene '{texto}')")
                elif ext == ".bsa" and not sin_bsa:
                    n_bsa += 1
                    bsa = LectorBSA(f)
                    for interna in bsa.archivos:
                        if Path(interna).suffix not in EXT_TEXTO:
                            continue
                        try:
                            datos = bsa.extraer(interna)
                        except Exception:
                            continue
                        bajo = datos.lower()
                        for texto, a in agujas:
                            j = bajo.find(a)
                            if j >= 0:
                                    anotar(f"[BSA]    {mod} :: {rel} -> {interna}\n"
                                       f"          ...{fragmento(datos, j, len(a))}...")
            except (OSError, ErrorFatal, struct.error, IndexError, ValueError) as e:
                print(f"  (no pude leer {mod} :: {rel}: {e})")
    resumen = (f"\nRevisados: {n_archivos:,} archivos de texto, {n_plugins:,} plugins, {n_bsa:,} BSA.\n"
               f"Coincidencias: {len(lineas)}")
    anotar(resumen)
    if not lineas[:-1]:
        anotar("No aparece en ningún archivo: el juego lo arma por partes (por ejemplo un nombre + ':').")
    (CARPETA / "buscar_texto_resultado.txt").write_text("\n".join(lineas), encoding="utf-8-sig")
    print(f"Guardado en buscar_texto_resultado.txt\n")


if __name__ == "__main__":
    try:
        main()
    except ErrorFatal as e:
        sys.exit(f"\nError: {e}")
