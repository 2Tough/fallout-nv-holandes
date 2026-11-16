#!/usr/bin/env python3
"""
wildcard_nl.py
Traduce al holandés los plugins (.esm/.esp) de un modlist de Mod Organizer 2 (FNV Wild Card)
reutilizando la caché y los scripts del proyecto (traducir_fnv.py y esm_nl.py).

No modifica ningún archivo del modlist. Crea copias traducidas de los plugins en un mod nuevo
de MO2, "[NL] Wild Card Nederlands": activado = holandés, desactivado = inglés.
Las copias tienen los mismos registros en el mismo orden (solo cambia el texto), así que no
hay problemas de orden de diálogos ni de orden de carga.

Va en la carpeta FNV_NL, junto a esm_nl.py, traducir_fnv.py y cache_traducciones.json.

Uso (PowerShell, desde FNV_NL):
  1) Diagnóstico (gratis, no escribe nada):
     python wildcard_nl.py contar
  2) XML para traducir (formato de xTranslator, lo lee traducir_fnv.py):
     python wildcard_nl.py xml
     python traducir_fnv.py contar         WildCard_en_de.xml
     python traducir_fnv.py traducir       WildCard_en_de.xml --limite 100      (prueba)
     python traducir_fnv.py traducir       WildCard_en_de.xml
     python traducir_fnv.py exportar-xedit WildCard_en_de.xml
     mkdir WILDCARD -Force; Copy-Item traducciones_nl.txt, campos_nl.txt WILDCARD
  3) Crear el mod traducido (MO2 cerrado):
     python wildcard_nl.py construir
     -> en MO2: F5, activar "[NL] Wild Card Nederlands" y ponerlo abajo del todo (máxima prioridad).

Opciones:
  --mo2 RUTA        carpeta del modlist (por defecto F:\\Mods\\FWC)
  --perfil NOMBRE   perfil de MO2 (por defecto el seleccionado en MO2)
  --campos ARCHIVO  campos de texto a leer (por defecto DLC\\campos_nl.txt o campos_nl.txt)
  --carpeta CARP    (construir) carpeta con traducciones_nl.txt y campos_nl.txt (por defecto WILDCARD)
  --gmst ARCHIVO    (construir) gmst_nl.txt con los textos del interfaz
"""

import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
MO2_POR_DEFECTO = r"F:\Mods\FWC"
MOD_NL = "[NL] Wild Card Nederlands"
CABECERA = 24
COMPRIMIDO = 0x00040000
EXT_PLUGIN = (".esm", ".esp")
OFICIALES = ["FalloutNV.esm", "DeadMoney.esm", "HonestHearts.esm", "OldWorldBlues.esm",
             "LonesomeRoad.esm", "GunRunnersArsenal.esm", "ClassicPack.esm", "MercenaryPack.esm",
             "TribalPack.esm", "CaravanPack.esm"]
TIPOS_DIALOGO = {"INFO", "DIAL", "QUST"}
USD_POR_MILLON = 4.0          # referencia del juego base: 2,6 M caracteres < 10 USD
ARCHIVO_XML = "WildCard_en_de.xml"


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
    """Igual que clave() de esm_nl.py y clave_xedit() de traducir_fnv.py."""
    return re.sub(r"[ \t\r\n]+", " ", texto).strip(" ")


def normalizar(texto):
    """Saltos de línea como los deja el XML de xTranslator (y la caché): solo \\n."""
    return texto.replace("\r\n", "\n").replace("\r", "\n")


def tiene_letras(texto):
    return re.search(r"[A-Za-z]", texto) is not None


XML_INVALIDO = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


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
        if not juego:
            raise ErrorFatal("No pude leer gamePath de ModOrganizer.ini.")
        self.data = Path(juego) / "Data"
        mods = valor_ini(txt, "mod_directory")
        self.mods = Path(mods.replace("%BASE_DIR%", str(self.raiz))) if mods else self.raiz / "mods"
        self.overwrite = self.raiz / "overwrite"
        self.perfil = perfil or valor_ini(txt, "selected_profile")
        self.dir_perfil = self.raiz / "profiles" / (self.perfil or "")
        if not self.perfil or not self.dir_perfil.is_dir():
            raise ErrorFatal(f"No encuentro el perfil '{self.perfil}'. Usa --perfil \"nombre\".")
        self.mods_activos = self._mods_activos()
        self.plugins = self._plugins()
        self._indices = {}

    def _mods_activos(self):
        """Mods activos de mayor a menor prioridad (modlist.txt tiene la mayor arriba)."""
        ruta = self.dir_perfil / "modlist.txt"
        if not ruta.exists():
            raise ErrorFatal(f"No existe {ruta}")
        activos = []
        for linea in leer_texto(ruta).splitlines():
            if linea.startswith("+"):
                nombre = linea[1:]
                if nombre != MOD_NL and not nombre.endswith("_separator"):
                    activos.append(nombre)
        return activos

    def _plugins(self):
        """Plugins activos en orden de carga."""
        ruta = self.dir_perfil / "plugins.txt"
        if not ruta.exists():
            raise ErrorFatal(f"No existe {ruta}")
        lineas = [l.strip() for l in leer_texto(ruta).splitlines() if l.strip() and not l.startswith("#")]
        if any(l.startswith("*") for l in lineas):
            activos = [l[1:] for l in lineas if l.startswith("*")]
        else:
            activos = lineas
        orden = activos
        ruta_orden = self.dir_perfil / "loadorder.txt"
        if ruta_orden.exists():
            minus = {a.lower() for a in activos}
            orden = [l.strip() for l in leer_texto(ruta_orden).splitlines()
                     if l.strip() and not l.startswith("#") and l.strip().lower() in minus]
            vistos = {o.lower() for o in orden}
            orden += [a for a in activos if a.lower() not in vistos]
        vistos = {o.lower() for o in orden}
        self.agregados = {o.lower() for o in OFICIALES if o.lower() not in vistos}
        delante = [o for o in OFICIALES if o.lower() in self.agregados]
        return delante + orden

    def _indice(self, carpeta):
        if carpeta not in self._indices:
            d = {}
            if carpeta.is_dir():
                for f in carpeta.iterdir():
                    if f.is_file() and f.suffix.lower() in EXT_PLUGIN:
                        d[f.name.lower()] = f
            self._indices[carpeta] = d
        return self._indices[carpeta]

    def buscar(self, plugin):
        """Archivo que el juego ve para este plugin (overwrite > mods por prioridad > Data)."""
        carpetas = [self.overwrite] + [self.mods / m for m in self.mods_activos] + [self.data]
        for c in carpetas:
            f = self._indice(c).get(plugin.lower())
            if f is not None:
                return f, c
        return None, None

    def origen(self, carpeta):
        if carpeta == self.data:
            return "juego (Stock New Vegas)"
        if carpeta == self.overwrite:
            return "overwrite"
        return carpeta.name


# ---------------------------------------------------------------- lectura de plugins

def leer_campos(ruta):
    campos = {}
    for linea in leer_texto(ruta).splitlines():
        linea = linea.strip()
        if len(linea) == 9 and linea[4] == ":":
            campos.setdefault(linea[:4], set()).add(linea[5:])
    if not campos:
        raise ErrorFatal(f"{ruta} no tiene campos (líneas como INFO:NAM1).")
    return campos


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


def descomprimir(cuerpo):
    tam = struct.unpack_from("<I", cuerpo, 0)[0]
    try:
        return zlib.decompress(cuerpo[4:])
    except zlib.error:
        d = zlib.decompressobj(-15)
        datos = d.decompress(cuerpo[6:])
        if len(datos) != tam:
            raise
        return datos


def como_texto(dato):
    con_nulo = dato.endswith(b"\x00")
    cuerpo = dato[:-1] if con_nulo else dato
    if b"\x00" in cuerpo:
        return None
    try:
        return cuerpo.decode("cp1252")
    except UnicodeDecodeError:
        return None


def textos_de_plugin(ruta, campos):
    """Lista de (tipo, campo, edid, texto) de los campos de texto del plugin."""
    buf = memoryview(Path(ruta).read_bytes())
    if bytes(buf[:4]) != b"TES4":
        raise ErrorFatal(f"{Path(ruta).name} no es un plugin de Fallout.")
    salida = []
    tipos = {t.encode() for t in campos}

    def recorrer(p, fin):
        while p + CABECERA <= fin:
            sig = bytes(buf[p:p + 4])
            tam = struct.unpack_from("<I", buf, p + 4)[0]
            if sig == b"GRUP":
                recorrer(p + CABECERA, p + tam)
                p += tam
                continue
            flags = struct.unpack_from("<I", buf, p + 8)[0]
            if sig in tipos:
                cuerpo = bytes(buf[p + CABECERA:p + CABECERA + tam])
                try:
                    datos = descomprimir(cuerpo) if flags & COMPRIMIDO else cuerpo
                except Exception:
                    datos = b""
                tipo = sig.decode()
                validos = campos[tipo]
                edid = ""
                for s, d in subregistros(datos):
                    nombre = s.decode("latin-1")
                    if nombre == "EDID":
                        edid = como_texto(d) or ""
                    elif nombre in validos:
                        t = como_texto(d)
                        if t is not None and t.strip() and tiene_letras(t):
                            salida.append((tipo, nombre, edid, normalizar(t)))
            p += CABECERA + tam

    tam_tes4 = struct.unpack_from("<I", buf, 4)[0]
    recorrer(CABECERA + tam_tes4, len(buf))
    return salida


def ruta_campos(opciones):
    if opciones.get("campos"):
        return Path(opciones["campos"])
    for c in (CARPETA / "DLC" / "campos_nl.txt", CARPETA / "campos_nl.txt"):
        if c.exists():
            return c
    raise ErrorFatal("No encuentro campos_nl.txt (ni en DLC\\ ni en FNV_NL). Usa --campos.")


def leer_cache():
    ruta = CARPETA / "cache_traducciones.json"
    if not ruta.exists():
        print("(No encontré cache_traducciones.json: todo contará como texto nuevo.)")
        return set()
    with open(ruta, encoding="utf-8") as f:
        cache = json.load(f)
    return {clave(normalizar(k)) for k, v in cache.items() if isinstance(v, str) and v.strip() and v != k}


def recoger(ml, campos):
    """[(plugin, ruta, origen, textos)] de todos los plugins activos."""
    resultado = []
    faltan = []
    for i, plugin in enumerate(ml.plugins, 1):
        ruta, carpeta = ml.buscar(plugin)
        if ruta is None:
            if plugin.lower() not in ml.agregados:
                faltan.append(plugin)
            continue
        print(f"\r  Leyendo {i}/{len(ml.plugins)}: {plugin[:60]:<60}", end="", flush=True)
        resultado.append((plugin, ruta, ml.origen(carpeta), textos_de_plugin(ruta, campos)))
    print("\r" + " " * 80 + "\r", end="")
    for f in faltan:
        print(f"  AVISO: no encontré el archivo de {f}")
    return resultado


# ---------------------------------------------------------------- comandos

def comando_contar(ml, opciones):
    campos = leer_campos(ruta_campos(opciones))
    cache = leer_cache()
    print(f"\nPerfil: {ml.perfil}\nPlugins activos: {len(ml.plugins)}\n")
    datos = recoger(ml, campos)

    vistos = set()
    filas = []
    tot_textos = tot_nuevos = car_dialogo = car_resto = 0
    for plugin, ruta, origen, textos in datos:
        nuevos = car = 0
        for tipo, campo, edid, t in textos:
            k = clave(t)
            if k in cache or k in vistos:
                continue
            vistos.add(k)
            nuevos += 1
            car += len(t)
            if tipo in TIPOS_DIALOGO:
                car_dialogo += len(t)
            else:
                car_resto += len(t)
        tot_textos += len(textos)
        tot_nuevos += nuevos
        filas.append((car, nuevos, len(textos), plugin, origen))

    print(f"{'Plugin':<52} {'textos':>8} {'nuevos':>7} {'caract. nuevos':>15}")
    print("-" * 85)
    for car, nuevos, n, plugin, origen in filas:
        if n:
            print(f"{plugin[:52]:<52} {n:>8,} {nuevos:>7,} {car:>15,}")
    total_car = car_dialogo + car_resto
    print("-" * 85)
    print(f"Textos en todos los plugins:       {tot_textos:,}")
    print(f"Textos nuevos (no están en caché): {tot_nuevos:,}")
    print(f"Caracteres nuevos:                 {total_car:,} "
          f"(diálogos/misiones {car_dialogo:,}, resto {car_resto:,})")
    print(f"Costo aproximado con Gemini:       ~{total_car / 1e6 * USD_POR_MILLON:.2f} USD")
    modificados = [(p, o) for p, o in ((d[0], d[2]) for d in datos)
                   if p in OFICIALES and not o.startswith("juego")]
    if modificados:
        print("\nOjo: Wild Card usa versiones propias de estos .esm oficiales (también se traducen):")
        for p, o in modificados:
            print(f"   {p}  <-  {o}")
    print("\nTop 15 por texto nuevo:")
    for car, nuevos, n, plugin, origen in sorted(filas, reverse=True)[:15]:
        if car:
            print(f"   {car:>9,}  {plugin}")
    print("\nSiguiente paso: python wildcard_nl.py xml\n")


def comando_xml(ml, opciones):
    campos = leer_campos(ruta_campos(opciones))
    print(f"\nPerfil: {ml.perfil}\nPlugins activos: {len(ml.plugins)}")
    datos = recoger(ml, campos)
    raiz = ET.Element("SSTXMLRessources")
    params = ET.SubElement(raiz, "Params")
    for k, v in (("Addon", "WildCard"), ("Source", "en"), ("Dest", "de"), ("Version", "2")):
        ET.SubElement(params, k).text = v
    contenido = ET.SubElement(raiz, "Content")
    vistos, n, saltados = set(), 0, 0
    for plugin, ruta, origen, textos in datos:
        for tipo, campo, edid, t in textos:
            if (tipo, campo, t) in vistos:
                continue
            vistos.add((tipo, campo, t))
            if XML_INVALIDO.search(t) or XML_INVALIDO.search(edid):
                saltados += 1
                continue
            s = ET.SubElement(contenido, "String", List="0", sID=f"{n:06X}")
            ET.SubElement(s, "EDID").text = edid
            rec = ET.SubElement(s, "REC", id=tipo, idx="1")
            rec.text = f"{tipo}:{campo}"
            ET.SubElement(s, "Source").text = t
            ET.SubElement(s, "Dest").text = t
            n += 1
    destino = CARPETA / ARCHIVO_XML
    ET.ElementTree(raiz).write(destino, encoding="utf-8", xml_declaration=True)
    print(f"\nTextos distintos: {n:,}" + (f" ({saltados} saltados por caracteres raros)" if saltados else ""))
    print(f"Archivo creado:   {destino}")
    print("\nSiguientes pasos:")
    print(f"   python traducir_fnv.py contar         {ARCHIVO_XML}")
    print(f"   python traducir_fnv.py traducir       {ARCHIVO_XML} --limite 100")
    print(f"   python traducir_fnv.py traducir       {ARCHIVO_XML}")
    print(f"   python traducir_fnv.py exportar-xedit {ARCHIVO_XML}")
    print("   mkdir WILDCARD -Force; Copy-Item traducciones_nl.txt, campos_nl.txt WILDCARD")
    print("   python wildcard_nl.py construir\n")


def ruta_gmst(opciones):
    if opciones.get("gmst"):
        r = Path(opciones["gmst"])
        if not r.exists():
            raise ErrorFatal(f"No existe {r}")
        return r
    for c in (CARPETA.parent / "FNVEdit 4.1.5f" / "Edit Scripts" / "gmst_nl.txt",
              CARPETA / "BASE" / "gmst_nl.txt", CARPETA / "gmst_nl.txt"):
        if c.exists():
            return c
    return None


def comando_construir(ml, opciones):
    sys.path.insert(0, str(CARPETA))
    try:
        import esm_nl
    except ImportError:
        raise ErrorFatal("No encuentro esm_nl.py en esta carpeta.")

    carpeta = Path(opciones.get("carpeta") or CARPETA / "WILDCARD")
    trad_txt, campos_txt = carpeta / "traducciones_nl.txt", carpeta / "campos_nl.txt"
    for r in (trad_txt, campos_txt):
        if not r.exists():
            raise ErrorFatal(f"No encuentro {r}. Haz antes 'exportar-xedit' y copia los archivos a {carpeta.name}.")
    traducciones = {clave(k): v for k, v in esm_nl.leer_pares(trad_txt).items()}
    campos = {}
    for t, s in leer_campos(campos_txt).items():
        campos[t.encode()] = {x.encode() for x in s}
    rg = ruta_gmst(opciones)
    gmst = {k.strip(): v for k, v in esm_nl.leer_pares(rg).items()} if rg else {}
    print(f"\n{len(traducciones):,} traducciones, {sum(len(v) for v in campos.values())} campos, "
          f"{len(gmst):,} textos del interfaz" + (f" ({rg})" if rg else " (sin gmst_nl.txt: menús en inglés)"))

    class TraductorPlugin(esm_nl.Traductor):
        def __init__(self, anadir_gmst):
            super().__init__({}, campos, gmst)
            self.traducciones = traducciones
            self.anadir_gmst = anadir_gmst

        def gmst_nuevos(self, buf, p):
            return super().gmst_nuevos(buf, p) if self.anadir_gmst else b""

    salida_mod = ml.mods / MOD_NL
    salida_mod.mkdir(parents=True, exist_ok=True)
    print(f"Perfil: {ml.perfil}\nMod de salida: {salida_mod}\n")

    n_archivos = n_textos = n_gmst = n_leidos = 0
    for i, plugin in enumerate(ml.plugins, 1):
        ruta, carpeta_origen = ml.buscar(plugin)
        destino = salida_mod / (ruta.name if ruta else plugin)
        if ruta is None:
            if plugin.lower() not in ml.agregados:
                print(f"\n  AVISO: no encontré {plugin}")
            continue
        print(f"\r  {i}/{len(ml.plugins)}: {plugin[:60]:<60}", end="", flush=True)
        n_leidos += 1
        original = ruta.read_bytes()
        t = TraductorPlugin(anadir_gmst=(plugin.lower() == "falloutnv.esm"))
        nuevo = t.archivo(memoryview(original))
        if nuevo == original:
            if destino.exists():
                destino.unlink()          # de una versión anterior; ya no hace falta
            continue
        comprobador = esm_nl.Traductor({}, {}, {}, forzar=True)
        if comprobador.archivo(memoryview(nuevo)) != nuevo or comprobador.n_fallos_lectura:
            print(f"\n  ERROR: la comprobación de {plugin} falló; se deja en inglés.")
            continue
        if comprobador.n_registros_total != t.n_registros_total + len(t.nuevas_formid):
            print(f"\n  ERROR: {plugin} cambió el número de registros; se deja en inglés.")
            continue
        destino.write_bytes(nuevo)
        n_archivos += 1
        n_textos += t.n_textos
        n_gmst += t.n_gmst_cambiados + len(t.nuevas_formid)
    print("\r" + " " * 80)
    print("=" * 60)
    print(f"Plugins traducidos:   {n_archivos:,} de {n_leidos:,}")
    print(f"Textos traducidos:    {n_textos:,}")
    print(f"Textos del interfaz:  {n_gmst:,}")
    print("=" * 60)
    print(f"En MO2: F5, activa \"{MOD_NL}\" y ponlo abajo del todo en la lista de mods (máxima prioridad).")
    print("Si MO2 pregunta por conflictos, este mod debe ganar.\n")


def main():
    args = sys.argv[1:]
    opciones = {}
    for nombre in ("mo2", "perfil", "campos", "carpeta", "gmst"):
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
    {"contar": comando_contar, "xml": comando_xml, "construir": comando_construir}[args[0]](ml, opciones)


if __name__ == "__main__":
    try:
        main()
    except ErrorFatal as e:
        sys.exit(f"\nError: {e}")
