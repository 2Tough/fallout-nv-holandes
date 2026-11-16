#!/usr/bin/env python3
"""
esm_nl.py
Traduce Fallout: New Vegas al holandés sin usar FNVEdit. Dos formas de hacerlo:

  A) Copia traducida de FalloutNV.esm (sustituye al original).
  B) Plugin FalloutNV_NL.esp (se carga encima del original, como cualquier mod).

En los dos casos ningún registro se mueve. En el .esp, cada tema de diálogo (DIAL) que tiene
alguna frase traducida se copia COMPLETO: el tema y todas sus frases (INFO), traducidas o no,
en el mismo orden que en FalloutNV.esm y con su PNAM original. Así el juego no puede
reordenar las frases (el problema del Doc Mitchell y el Vigor Tester con el .esp de FNVEdit).

Usa los mismos archivos que Traduccion_NL.pas: traducciones_nl.txt y campos_nl.txt
(y gmst_nl.txt para los textos del interfaz).

Uso (desde FNV_NL):
  1) Prueba sin traducir (debe salir "IDÉNTICO"):
     python esm_nl.py probar   "ORIGINAL.esm"

  2A) Copia traducida del .esm:
     python esm_nl.py traducir "ORIGINAL.esm" "FalloutNV_traducido.esm" "...\\Edit Scripts"
     -> copiar a Data con el nombre FalloutNV.esm (guarda antes el original).

  2B) Plugin .esp:
     python esm_nl.py esp      "ORIGINAL.esm" "FalloutNV_NL.esp" "...\\Edit Scripts" [--pnam orden]
     -> copiar FalloutNV_NL.esp a Data y activarlo; Data debe tener el FalloutNV.esm ORIGINAL.
     DLC: python esm_nl.py esp "DeadMoney_original.esm" "DeadMoney_NL.esp" "DLC"
     -> maestros FalloutNV.esm + DeadMoney.esm (el nombre sale quitando "_original").
        Orden de carga: FalloutNV_NL.esp primero, luego los .esp de los DLC (en el orden de los DLC).
     --pnam orden: además, rellena/corrige PNAM para que cada frase apunte a la anterior en el
                   archivo (por defecto se deja el PNAM original intacto).

  3) Comprobar el .esp (orden de las frases tema por tema, sin FNVEdit):
     python esm_nl.py comprobar-esp "ORIGINAL.esm" "FalloutNV_NL.esp"

  (la carpeta de "Edit Scripts" debe contener traducciones_nl.txt, campos_nl.txt y, opcional,
   gmst_nl.txt)
"""

import hashlib
import re
import struct
import sys
import zlib
from pathlib import Path

CABECERA = 24                     # bytes de cabecera de registro y de grupo (Fallout 3 / New Vegas)
COMPRIMIDO = 0x00040000           # bandera de registro comprimido
ES_MAESTRO = 0x00000001           # bandera ESM en la cabecera TES4
GRUPO_TEMA = 7                    # tipo de grupo "Topic Children" (las INFO de un DIAL)
GRUPOS_HIJOS = {1, 6, 7, 8, 9, 10}  # grupos que van justo detrás de su registro "padre"
PRIMERA_FORMID_ESP = 0x800        # primera FormID libre en un plugin
AUTOR_ESP = "FNV_NL (esm_nl.py)"

# Correcciones a mano: (tipo, Editor ID, subregistro) -> texto
CORRECCIONES = {
    ("AVIF", "AVEndurance", "FULL"): "Uithouding",
}


class ErrorFatal(Exception):
    pass


DANADOS = []      # FormIDs de registros con la suma de control zlib dañada (el juego los lee igual)


def descomprimir(cuerpo, formid):
    """Datos de un registro comprimido. Algunos registros del FalloutNV.esm original tienen la
    suma de control (Adler-32) incorrecta; el juego no la comprueba, así que aquí tampoco."""
    tam = struct.unpack_from("<I", cuerpo, 0)[0]
    try:
        return zlib.decompress(cuerpo[4:])
    except zlib.error:
        d = zlib.decompressobj(-15)                 # deflate sin cabecera ni suma de control
        datos = d.decompress(cuerpo[6:])
        if len(datos) != tam:
            raise ErrorFatal(f"No pude descomprimir el registro {formid:08X}.")
        DANADOS.append(formid)
        return datos


# ---------------------------------------------------------------- archivos de traducción

def leer_texto(ruta):
    datos = Path(ruta).read_bytes()
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return datos.decode("cp1252")


def leer_pares(ruta):
    pares = {}
    if not Path(ruta).exists():
        return pares
    for linea in leer_texto(ruta).splitlines():
        p = linea.find("\t")
        if p > 0:
            pares.setdefault(linea[:p], linea[p + 1:])
    return pares


def clave(texto):
    """Debe coincidir con clave_xedit() de traducir_fnv.py y Clave() de Traduccion_NL.pas."""
    return re.sub(r"[ \t\r\n]+", " ", texto).strip(" ")


def desescapar(s, salto):
    return s.replace("{{NL}}", salto).replace("{{TAB}}", "\t")


# ---------------------------------------------------------------- subregistros

def leer_subregistros(datos):
    subs, p, grande = [], 0, None
    while p < len(datos):
        sig = bytes(datos[p:p + 4])
        tam = struct.unpack_from("<H", datos, p + 4)[0]
        p += 6
        if grande is not None:
            tam, grande = grande, None
        if sig == b"XXXX":
            grande = struct.unpack_from("<I", datos, p)[0]
            p += tam
            continue
        subs.append([sig, bytes(datos[p:p + tam])])
        p += tam
    return subs


def escribir_subregistros(subs):
    salida = bytearray()
    for sig, dato in subs:
        if len(dato) > 0xFFFF:
            salida += b"XXXX" + struct.pack("<HI", 4, len(dato)) + sig + struct.pack("<H", 0)
        else:
            salida += sig + struct.pack("<H", len(dato))
        salida += dato
    return bytes(salida)


def texto_de(dato):
    """(texto, terminado_en_nulo) o None si no parece un texto."""
    con_nulo = dato.endswith(b"\x00")
    cuerpo = dato[:-1] if con_nulo else dato
    if b"\x00" in cuerpo:
        return None
    try:
        return cuerpo.decode("cp1252"), con_nulo
    except UnicodeDecodeError:
        return None


def datos_registro(registro):
    """Subregistros (en bytes) de un registro completo (cabecera incluida)."""
    tam, flags, formid = struct.unpack_from("<III", registro, 4)
    cuerpo = bytes(registro[CABECERA:CABECERA + tam])
    return descomprimir(cuerpo, formid) if flags & COMPRIMIDO else cuerpo


def rehacer_registro(registro, datos):
    """Mismo registro (misma cabecera) con otros datos; se vuelve a comprimir si lo estaba."""
    flags = struct.unpack_from("<I", registro, 8)[0]
    if flags & COMPRIMIDO:
        datos = struct.pack("<I", len(datos)) + zlib.compress(datos, 6)
    cab = bytearray(registro[:CABECERA])
    struct.pack_into("<I", cab, 4, len(datos))
    return bytes(cab) + datos


# ---------------------------------------------------------------- recorrido del archivo

class Traductor:
    def __init__(self, traducciones, campos, gmst, forzar=False):
        self.forzar = forzar                      # modo prueba: reconstruir todo y comparar
        self.n_fallos_lectura = 0
        self.traducciones = {clave(k): v for k, v in traducciones.items()}
        self.campos = campos                      # {b"INFO": {b"NAM1", ...}, ...}
        self.gmst = gmst                          # {EDID: texto}
        self.gmst_usados = set()
        self.nuevas_formid = []
        self.n_textos = 0
        self.n_registros = 0
        self.n_gmst_cambiados = 0
        self.n_sin_codificar = 0
        self.max_formid = 0
        self.n_registros_total = 0

    # -------- traducción de un registro
    def traducir_registro(self, tipo, datos):
        subs = leer_subregistros(datos)
        edid = None
        for sig, dato in subs:
            if sig == b"EDID":
                t = texto_de(dato)
                edid = t[0] if t else None
                break
        cambios = 0
        sigs = self.campos.get(tipo, set())
        for s in subs:
            sig, dato = s
            nuevo = None
            correccion = CORRECCIONES.get((tipo.decode(), edid, sig.decode("latin-1")))
            if tipo == b"GMST" and sig == b"DATA" and edid in self.gmst:
                t = texto_de(dato)
                if t is not None:
                    nuevo = (desescapar(self.gmst[edid], "\r\n"), t[1])
                    self.gmst_usados.add(edid)
                    self.n_gmst_cambiados += 1
            elif correccion is not None:
                t = texto_de(dato)
                if t is not None:
                    nuevo = (correccion, t[1])
            elif sig in sigs:
                t = texto_de(dato)
                if t is not None:
                    original, con_nulo = t
                    destino = self.traducciones.get(clave(original))
                    if destino is not None and clave(original):
                        salto = "\r\n" if "\r\n" in original else "\n"
                        inicio = original[:len(original) - len(original.lstrip(" \t\r\n"))]
                        fin = original[len(original.rstrip(" \t\r\n")):] if original.strip(" \t\r\n") else ""
                        nuevo = (inicio + desescapar(destino, salto) + fin, con_nulo)
            if nuevo is not None:
                texto, con_nulo = nuevo
                try:
                    codificado = texto.encode("cp1252")
                except UnicodeEncodeError:
                    codificado = texto.encode("cp1252", errors="replace")
                    self.n_sin_codificar += 1
                if con_nulo:
                    codificado += b"\x00"
                if codificado != dato:
                    s[1] = codificado
                    cambios += 1
        if not cambios:
            return None
        if tipo != b"GMST":
            self.n_textos += cambios
        return escribir_subregistros(subs)

    def registro(self, buf, p):
        tipo = bytes(buf[p:p + 4])
        tam, flags, formid = struct.unpack_from("<III", buf, p + 4)
        fin = p + CABECERA + tam
        crudo = buf[p:fin]
        if self.forzar:
            cuerpo = bytes(buf[p + CABECERA:fin])
            datos = descomprimir(cuerpo, formid) if flags & COMPRIMIDO else cuerpo
            if escribir_subregistros(leer_subregistros(datos)) != datos:
                self.n_fallos_lectura += 1
            return bytes(crudo), fin, True
        if tipo == b"GMST" or tipo in self.campos:
            cuerpo = bytes(buf[p + CABECERA:fin])
            if flags & COMPRIMIDO:
                datos = descomprimir(cuerpo, formid)
            else:
                datos = cuerpo
            nuevo = self.traducir_registro(tipo, datos)
            if nuevo is not None:
                self.n_registros += 1
                if flags & COMPRIMIDO:
                    nuevo = struct.pack("<I", len(nuevo)) + zlib.compress(nuevo, 6)
                cab = bytearray(buf[p:p + CABECERA])
                struct.pack_into("<I", cab, 4, len(nuevo))
                return bytes(cab) + nuevo, fin, True
        return crudo, fin, False

    def grupo(self, buf, p):
        tam = struct.unpack_from("<I", buf, p + 4)[0]
        etiqueta = bytes(buf[p + 8:p + 12])
        tipo_grupo = struct.unpack_from("<i", buf, p + 12)[0]
        fin = p + tam
        partes = []
        cambiado = False
        q = p + CABECERA
        while q < fin:
            if buf[q:q + 4] == b"GRUP":
                trozo, q, c = self.grupo(buf, q)
            else:
                trozo, q, c = self.registro(buf, q)
            partes.append(trozo)
            cambiado = cambiado or c
        if tipo_grupo == 0 and etiqueta == b"GMST":
            extra = self.gmst_nuevos(buf, p + CABECERA)
            if extra:
                partes.append(extra)
                cambiado = True
        if not cambiado:
            return buf[p:fin], fin, False       # grupo sin cambios: se copia tal cual
        contenido = b"".join(partes)
        cab = bytearray(buf[p:p + CABECERA])
        struct.pack_into("<I", cab, 4, CABECERA + len(contenido))
        return bytes(cab) + contenido, fin, True

    def nueva_formid(self):
        self.max_formid += 1
        self.nuevas_formid.append(self.max_formid)
        return self.max_formid

    def gmst_nuevos(self, buf, p_primer_registro):
        """Registros GMST nuevos para los textos del interfaz que no existen en el .esm."""
        faltan = [e for e in self.gmst if e not in self.gmst_usados]
        if not faltan:
            return b""
        # Copiar versión/flags de cabecera del primer GMST existente
        modelo = bytearray(buf[p_primer_registro:p_primer_registro + CABECERA])
        salida = bytearray()
        for edid in faltan:
            formid = self.nueva_formid()
            subs = [[b"EDID", edid.encode("cp1252") + b"\x00"],
                    [b"DATA", desescapar(self.gmst[edid], "\r\n").encode("cp1252", errors="replace") + b"\x00"]]
            datos = escribir_subregistros(subs)
            cab = bytearray(modelo)
            struct.pack_into("<III", cab, 4, len(datos), 0, formid)
            salida += cab + datos
        return bytes(salida)

    # -------- pasada previa: FormID máxima
    def escanear(self, buf, p, fin):
        while p < fin:
            if buf[p:p + 4] == b"GRUP":
                tam = struct.unpack_from("<I", buf, p + 4)[0]
                self.escanear(buf, p + CABECERA, p + tam)
                p += tam
            else:
                tam, _, formid = struct.unpack_from("<III", buf, p + 4)
                if formid < 0x01000000:
                    self.max_formid = max(self.max_formid, formid)
                self.n_registros_total += 1
                p += CABECERA + tam

    def archivo(self, buf):
        if bytes(buf[:4]) != b"TES4":
            raise ErrorFatal("No es un archivo .esm/.esp de Fallout (falta la cabecera TES4).")
        self.escanear(buf, 0, len(buf))
        tam_tes4 = struct.unpack_from("<I", buf, 4)[0]
        p = CABECERA + tam_tes4
        cabecera_tes4 = bytes(buf[:p])
        partes = []
        while p < len(buf):
            if buf[p:p + 4] != b"GRUP":
                raise ErrorFatal(f"Estructura inesperada en la posición {p}.")
            trozo, p, _ = self.grupo(buf, p)
            partes.append(trozo)
        if self.nuevas_formid:
            cabecera_tes4 = self.actualizar_hedr(cabecera_tes4, len(self.nuevas_formid))
        return cabecera_tes4 + b"".join(bytes(x) for x in partes)

    def actualizar_hedr(self, tes4, nuevos):
        datos = leer_subregistros(tes4[CABECERA:])
        for s in datos:
            if s[0] == b"HEDR" and len(s[1]) >= 12:
                version, num, siguiente = struct.unpack_from("<fiI", s[1])
                s[1] = struct.pack("<fiI", version, num + nuevos, max(siguiente, self.max_formid + 1)) + s[1][12:]
        cuerpo = escribir_subregistros(datos)
        cab = bytearray(tes4[:CABECERA])
        struct.pack_into("<I", cab, 4, len(cuerpo))
        return bytes(cab) + cuerpo


# ---------------------------------------------------------------- plugin .esp

class TraductorESP(Traductor):
    """Escribe solo lo que cambia, como un plugin que depende de FalloutNV.esm.

    Reglas:
      - Registro traducido -> se incluye (override).
      - Grupo con algo incluido -> se incluye con la misma cabecera, solo con lo incluido.
      - Grupo de hijos (mundo, celda, tema) incluido -> se incluye también su registro padre
        (el que va justo antes: WRLD, CELL o DIAL), aunque no tenga cambios.
      - Tema de diálogo (DIAL) con algo incluido -> se incluye ENTERO: el DIAL y todas sus INFO,
        en el orden del archivo original y con su PNAM original (o corregido con --pnam orden).
      - GMST nuevos -> FormID 01000800, 01000801... (01 = este plugin, al tener un solo maestro).
    """

    def __init__(self, traducciones, campos, gmst, pnam="original", nombre_maestro="FalloutNV.esm"):
        super().__init__(traducciones, campos, gmst)
        self.pnam = pnam
        self.nombre_maestro = nombre_maestro      # nombre en Data del .esm de origen (FalloutNV.esm, DeadMoney.esm...)
        self.maestros = []                        # maestros del .plugin: los del .esm de origen + él mismo
        self.indice_propio = 1                    # índice de las FormID nuevas (= número de maestros)
        self.max_formid = PRIMERA_FORMID_ESP - 1
        self.n_temas = 0
        self.n_info_sin_traducir = 0
        self.n_temas_pnam_distinto = 0
        self.n_pnam_cambiados = 0
        self.n_overrides = 0

    def escanear(self, buf, p, fin):
        maximo = self.max_formid
        super().escanear(buf, p, fin)
        self.max_formid = maximo                  # las FormID nuevas son del plugin, no del .esm

    def nueva_formid(self):
        self.max_formid += 1
        self.nuevas_formid.append(self.max_formid)
        return (self.indice_propio << 24) | self.max_formid

    # -------- PNAM
    @staticmethod
    def leer_pnam(datos):
        for sig, dato in leer_subregistros(datos):
            if sig == b"PNAM" and len(dato) >= 4:
                return struct.unpack_from("<I", dato)[0]
        return None

    @staticmethod
    def poner_pnam(datos, formid):
        subs = leer_subregistros(datos)
        for s in subs:
            if s[0] == b"PNAM":
                s[1] = struct.pack("<I", formid)
                return escribir_subregistros(subs)
        # No tenía PNAM: se añade después de DATA/QSTI/TPIC/NAM3 (como hace FNVEdit)
        pos = 0
        for i, (sig, _) in enumerate(subs):
            if sig in (b"EDID", b"DATA", b"QSTI", b"TPIC", b"NAM3"):
                pos = i + 1
        subs.insert(pos, [b"PNAM", struct.pack("<I", formid)])
        return escribir_subregistros(subs)

    # -------- tema completo
    def tema_completo(self, buf, p, partes_traducidas):
        """Grupo de hijos de un DIAL con TODAS sus INFO, en el orden original."""
        tam = struct.unpack_from("<I", buf, p + 4)[0]
        fin = p + tam
        anterior = 0
        distinto = False
        salida = []
        for trozo, traducido in partes_traducidas:
            if bytes(trozo[:4]) == b"GRUP":           # no debería pasar en un tema; se copia
                salida.append(bytes(trozo))
                continue
            formid = struct.unpack_from("<I", trozo, 12)[0]
            if not traducido:
                self.n_info_sin_traducir += 1
            if bytes(trozo[:4]) == b"INFO":
                datos = datos_registro(trozo)
                actual = self.leer_pnam(datos)
                if actual != anterior and not (actual is None and anterior == 0):
                    distinto = True
                if self.pnam == "orden" and actual != anterior:
                    trozo = rehacer_registro(trozo, self.poner_pnam(datos, anterior))
                    self.n_pnam_cambiados += 1
                anterior = formid
            salida.append(bytes(trozo))
        if distinto:
            self.n_temas_pnam_distinto += 1
        self.n_temas += 1
        contenido = b"".join(salida)
        cab = bytearray(buf[p:p + CABECERA])
        struct.pack_into("<I", cab, 4, CABECERA + len(contenido))
        return bytes(cab) + contenido, fin

    def grupo_esp(self, buf, p, tema_forzado=False):
        """Devuelve (bytes del grupo o None si no hay nada que incluir, posición final)."""
        tam = struct.unpack_from("<I", buf, p + 4)[0]
        etiqueta = bytes(buf[p + 8:p + 12])
        tipo_grupo = struct.unpack_from("<i", buf, p + 12)[0]
        fin = p + tam

        if tipo_grupo == GRUPO_TEMA:
            partes, algo = [], False
            q = p + CABECERA
            while q < fin:
                if buf[q:q + 4] == b"GRUP":
                    trozo, q, c = super().grupo(buf, q)
                else:
                    trozo, q, c = self.registro(buf, q)
                partes.append((trozo, c))
                algo = algo or c
            if not (algo or tema_forzado):
                return None, fin
            return self.tema_completo(buf, p, partes)

        # elementos: [tipo ('R'/'G'), bytes o None, traducido, tipo_de_grupo]
        elementos = []
        q = p + CABECERA
        forzar_siguiente = False
        while q < fin:
            if buf[q:q + 4] == b"GRUP":
                sub_tipo = struct.unpack_from("<i", buf, q + 12)[0]
                trozo, q = self.grupo_esp(buf, q, tema_forzado=forzar_siguiente and sub_tipo == GRUPO_TEMA)
                elementos.append(["G", trozo, trozo is not None, sub_tipo])
                forzar_siguiente = False
            else:
                es_dial = buf[q:q + 4] == b"DIAL"
                trozo, q, c = self.registro(buf, q)
                elementos.append(["R", bytes(trozo), c, None])
                forzar_siguiente = es_dial and c      # DIAL traducido -> su tema entero
        # Grupo de hijos incluido -> incluir su registro padre (el anterior)
        for i, e in enumerate(elementos):
            if e[0] == "G" and e[2] and e[3] in GRUPOS_HIJOS and i > 0 and elementos[i - 1][0] == "R":
                elementos[i - 1][2] = True
        partes = [e[1] for e in elementos if e[2]]
        self.n_overrides += sum(1 for e in elementos if e[0] == "R" and e[2])
        if tipo_grupo == 0 and etiqueta == b"GMST":
            extra = self.gmst_nuevos(buf, p + CABECERA)
            if extra:
                partes.append(extra)
        if not partes:
            return None, fin
        contenido = b"".join(partes)
        cab = bytearray(buf[p:p + CABECERA])
        struct.pack_into("<I", cab, 4, CABECERA + len(contenido))
        return bytes(cab) + contenido, fin

    def cabecera_esp(self, tes4_original, n_registros):
        """TES4 nuevo: sin bandera ESM; maestros = los del .esm de origen + el propio .esm.
        Así los índices de FormID de los registros copiados siguen siendo válidos sin cambiarlos
        (en DeadMoney.esm, 00 = FalloutNV.esm y 01 = DeadMoney.esm; en DeadMoney_NL.esp, igual)."""
        version = 1.34
        for sig, dato in leer_subregistros(tes4_original[CABECERA:]):
            if sig == b"HEDR" and len(dato) >= 4:
                version = struct.unpack_from("<f", dato)[0]
        subs = [
            [b"HEDR", struct.pack("<fiI", version, n_registros, self.max_formid + 1)],
            [b"CNAM", AUTOR_ESP.encode("cp1252") + b"\x00"],
        ]
        for m in self.maestros:
            subs += [[b"MAST", m.encode("cp1252") + b"\x00"], [b"DATA", struct.pack("<Q", 0)]]
        datos = escribir_subregistros(subs)
        cab = bytearray(tes4_original[:CABECERA])
        struct.pack_into("<III", cab, 4, len(datos), 0, 0)       # tamaño, sin banderas, FormID 0
        return bytes(cab) + datos

    def archivo(self, buf):
        if bytes(buf[:4]) != b"TES4":
            raise ErrorFatal("No es un archivo .esm/.esp de Fallout (falta la cabecera TES4).")
        flags = struct.unpack_from("<I", buf, 8)[0]
        if not flags & ES_MAESTRO:
            raise ErrorFatal("El archivo de entrada debe ser un .esm original (FalloutNV.esm o un DLC), no un .esp.")
        self.escanear(buf, 0, len(buf))
        tam_tes4 = struct.unpack_from("<I", buf, 4)[0]
        p = CABECERA + tam_tes4
        tes4 = bytes(buf[:p])
        propios = [texto_de(d)[0] for s, d in leer_subregistros(tes4[CABECERA:]) if s == b"MAST" and texto_de(d)]
        self.maestros = propios + [self.nombre_maestro]
        self.indice_propio = len(self.maestros)
        partes = []
        while p < len(buf):
            if buf[p:p + 4] != b"GRUP":
                raise ErrorFatal(f"Estructura inesperada en la posición {p}.")
            trozo, p = self.grupo_esp(buf, p)
            if trozo is not None:
                partes.append(trozo)
        cuerpo = b"".join(partes)
        contador = Traductor({}, {}, {})
        contador.escanear(memoryview(cuerpo), 0, len(cuerpo))
        return self.cabecera_esp(tes4, contador.n_registros_total) + cuerpo


# ---------------------------------------------------------------- índice de temas (comprobación)

def temas_de(buf):
    """{FormID del DIAL: [(FormID de cada INFO, PNAM), ...]} en el orden del archivo."""
    temas = {}

    def recorrer(p, fin, dial_actual):
        while p < fin:
            if buf[p:p + 4] == b"GRUP":
                tam = struct.unpack_from("<I", buf, p + 4)[0]
                tipo_grupo = struct.unpack_from("<i", buf, p + 12)[0]
                if tipo_grupo == GRUPO_TEMA:
                    dial = struct.unpack_from("<I", buf, p + 8)[0]
                    lista = temas.setdefault(dial, [])
                    q = p + CABECERA
                    while q < p + tam:
                        t, _, formid = struct.unpack_from("<III", buf, q + 4)
                        if bytes(buf[q:q + 4]) == b"INFO":
                            registro = bytes(buf[q:q + CABECERA + t])
                            lista.append((formid, TraductorESP.leer_pnam(datos_registro(registro))))
                        q += CABECERA + t
                else:
                    recorrer(p + CABECERA, p + tam, dial_actual)
                p += tam
            else:
                tam = struct.unpack_from("<I", buf, p + 4)[0]
                p += CABECERA + tam

    tam_tes4 = struct.unpack_from("<I", buf, 4)[0]
    recorrer(CABECERA + tam_tes4, len(buf), None)
    return temas


# ---------------------------------------------------------------- comandos

def huella(datos):
    return hashlib.sha1(datos).hexdigest()


def comando_probar(ruta):
    buf = memoryview(Path(ruta).read_bytes())
    print(f"\nLeyendo {Path(ruta).name} ({len(buf) / 1e6:.1f} MB)...")
    t = Traductor({}, {}, {}, forzar=True)
    salida = t.archivo(buf)
    print(f"Registros: {t.n_registros_total:,}")
    if DANADOS:
        print(f"Registros con la suma de control dañada en el original (normal, se copian tal cual): "
              f"{', '.join(f'{x:08X}' for x in sorted(set(DANADOS)))}")
    if salida == bytes(buf) and t.n_fallos_lectura == 0:
        print("Resultado: IDÉNTICO al original. El programa lee y escribe bien el archivo.\n")
    else:
        print(f"Resultado: DISTINTO del original ({t.n_fallos_lectura} registros mal leídos). "
              "No uses este programa: avisa con este mensaje.\n")


def cargar_traducciones(carpeta):
    carpeta = Path(carpeta)
    ruta_trad, ruta_campos = carpeta / "traducciones_nl.txt", carpeta / "campos_nl.txt"
    for r in (ruta_trad, ruta_campos):
        if not r.exists():
            raise ErrorFatal(f"No encuentro {r}")
    traducciones = leer_pares(ruta_trad)
    campos = {}
    for linea in leer_texto(ruta_campos).splitlines():
        linea = linea.strip()
        if len(linea) == 9 and linea[4] == ":":
            campos.setdefault(linea[:4].encode(), set()).add(linea[5:].encode())
    gmst = {k.strip(): v for k, v in leer_pares(carpeta / "gmst_nl.txt").items()}
    print(f"\n{len(traducciones):,} traducciones, {sum(len(v) for v in campos.values())} tipos de campo, "
          f"{len(gmst):,} textos del interfaz.")
    if not gmst:
        print("(No encontré gmst_nl.txt: los menús quedarán en inglés.)")
    return traducciones, campos, gmst


def comando_traducir(ruta, destino, carpeta):
    traducciones, campos, gmst = cargar_traducciones(carpeta)
    original = Path(ruta).read_bytes()
    if Path(destino).resolve() == Path(ruta).resolve():
        raise ErrorFatal("El archivo de salida no puede ser el mismo que el original.")
    print(f"Leyendo {Path(ruta).name} ({len(original) / 1e6:.1f} MB)...")
    t = Traductor(traducciones, campos, gmst)
    salida = t.archivo(memoryview(original))

    # Comprobación: el archivo nuevo se puede volver a leer entero
    comprobador = Traductor({}, {}, {}, forzar=True)
    if comprobador.archivo(memoryview(salida)) != salida or comprobador.n_fallos_lectura:
        raise ErrorFatal("La comprobación del archivo nuevo falló. No lo uses.")

    Path(destino).write_bytes(salida)
    print("\n" + "=" * 60)
    print(f"Textos traducidos:           {t.n_textos:,} en {t.n_registros:,} registros")
    print(f"Textos del interfaz:         {t.n_gmst_cambiados:,} cambiados, {len(t.nuevas_formid):,} añadidos")
    if t.n_sin_codificar:
        print(f"Con letras no admitidas:     {t.n_sin_codificar} (se sustituyeron por '?')")
    print(f"Registros en el original:    {t.n_registros_total:,}")
    print(f"Registros en el nuevo:       {comprobador.n_registros_total:,}")
    print(f"Archivo creado:              {destino} ({len(salida) / 1e6:.1f} MB)")
    print("=" * 60 + "\n")


def comprobar_orden(esm, esp, pnam):
    """Lista de problemas: temas del .esp cuyas INFO no coinciden con las del .esm."""
    temas_esm, temas_esp = temas_de(esm), temas_de(esp)
    problemas = []
    for dial, lista in temas_esp.items():
        original = temas_esm.get(dial)
        if original is None:
            problemas.append(f"{dial:08X}: el tema no existe en el .esm")
            continue
        if [f for f, _ in lista] != [f for f, _ in original]:
            problemas.append(f"{dial:08X}: frases u orden distintos "
                             f"({len(lista)} en el .esp, {len(original)} en el .esm)")
            continue
        if pnam == "original" and [x for _, x in lista] != [x for _, x in original]:
            problemas.append(f"{dial:08X}: PNAM distinto del original")
    return problemas, len(temas_esp)


def comando_esp(ruta, destino, carpeta, pnam):
    traducciones, campos, gmst = cargar_traducciones(carpeta)
    original = Path(ruta).read_bytes()
    if Path(destino).resolve() == Path(ruta).resolve():
        raise ErrorFatal("El archivo de salida no puede ser el mismo que el original.")
    # Nombre del .esm en Data: DeadMoney_original.esm -> DeadMoney.esm
    base = Path(ruta).stem
    if base.lower().endswith("_original"):
        base = base[:-len("_original")]
    nombre_maestro = base + ".esm"
    print(f"Leyendo {Path(ruta).name} ({len(original) / 1e6:.1f} MB)...")
    t = TraductorESP(traducciones, campos, gmst, pnam=pnam, nombre_maestro=nombre_maestro)
    salida = t.archivo(memoryview(original))

    # Comprobación 1: el .esp se puede volver a leer entero
    comprobador = Traductor({}, {}, {}, forzar=True)
    if comprobador.archivo(memoryview(salida)) != salida or comprobador.n_fallos_lectura:
        raise ErrorFatal("La comprobación del archivo nuevo falló. No lo uses.")
    # Comprobación 2: cada tema del .esp tiene las mismas frases y en el mismo orden que el .esm
    problemas, n_temas = comprobar_orden(memoryview(original), memoryview(salida), pnam)
    if problemas:
        for linea in problemas[:20]:
            print("  " + linea)
        raise ErrorFatal(f"{len(problemas)} temas con el orden distinto. No uses el .esp.")

    Path(destino).write_bytes(salida)
    print("\n" + "=" * 60)
    print(f"Textos traducidos:           {t.n_textos:,} en {t.n_registros:,} registros")
    print(f"Textos del interfaz:         {t.n_gmst_cambiados:,} cambiados, {len(t.nuevas_formid):,} añadidos")
    if t.n_sin_codificar:
        print(f"Con letras no admitidas:     {t.n_sin_codificar} (se sustituyeron por '?')")
    print(f"Temas de diálogo completos:  {t.n_temas:,} (incluyen {t.n_info_sin_traducir:,} frases sin "
          f"traducir, copiadas tal cual)")
    print(f"Temas con PNAM distinto del orden del archivo: {t.n_temas_pnam_distinto:,}")
    if pnam == "orden":
        print(f"PNAM corregidos (--pnam orden): {t.n_pnam_cambiados:,}")
    print(f"Registros en el .esp:        {comprobador.n_registros_total:,}")
    print(f"Comprobación de orden:       {n_temas:,} temas, todos IGUALES al .esm")
    print(f"Archivo creado:              {destino} ({len(salida) / 1e6:.1f} MB)")
    print(f"Maestros del .esp:           {', '.join(t.maestros)}")
    print("=" * 60)
    print(f"Data debe tener {nombre_maestro} ORIGINAL; activa {Path(destino).name} después de él "
          "(y los .esp de los DLC después de FalloutNV_NL.esp).\n")


def comando_comprobar_esp(ruta_esm, ruta_esp):
    esm = memoryview(Path(ruta_esm).read_bytes())
    esp = memoryview(Path(ruta_esp).read_bytes())
    problemas, n_temas = comprobar_orden(esm, esp, "orden")
    temas_esm = temas_de(esm)
    incompletos = sum(1 for d, l in temas_de(esp).items() if len(l) != len(temas_esm.get(d, [])))
    print(f"\nTemas de diálogo en {Path(ruta_esp).name}: {n_temas:,}")
    print(f"Temas incompletos (faltan frases del .esm): {incompletos:,}")
    if problemas:
        print(f"Temas con frases u orden distintos: {len(problemas):,}")
        for linea in problemas[:30]:
            print("  " + linea)
    else:
        print("Todas las frases están en el mismo orden que en el .esm.")
    print()


def main():
    args = sys.argv[1:]
    pnam = "original"
    if "--pnam" in args:
        i = args.index("--pnam")
        if i + 1 >= len(args) or args[i + 1] not in ("original", "orden"):
            raise ErrorFatal("--pnam debe ser 'original' u 'orden'.")
        pnam = args[i + 1]
        del args[i:i + 2]
    if len(args) >= 2 and args[0] == "probar":
        comando_probar(args[1])
    elif len(args) >= 4 and args[0] == "traducir":
        comando_traducir(args[1], args[2], args[3])
    elif len(args) >= 4 and args[0] == "esp":
        comando_esp(args[1], args[2], args[3], pnam)
    elif len(args) >= 3 and args[0] == "comprobar-esp":
        comando_comprobar_esp(args[1], args[2])
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        main()
    except ErrorFatal as e:
        sys.exit(f"\nError: {e}")
