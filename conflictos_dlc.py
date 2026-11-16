import struct, sys
from collections import Counter
from pathlib import Path

def registros(buf):
    salida = {}
    def recorrer(p, fin):
        while p < fin:
            if buf[p:p + 4] == b"GRUP":
                tam = struct.unpack_from("<I", buf, p + 4)[0]
                recorrer(p + 24, p + tam)
                p += tam
            else:
                tipo = bytes(buf[p:p + 4]).decode("latin-1")
                tam, _, formid = struct.unpack_from("<III", buf, p + 4)
                salida[formid] = tipo
                p += 24 + tam
    recorrer(24 + struct.unpack_from("<I", buf, 4)[0], len(buf))
    return salida

esp = memoryview(Path(sys.argv[1]).read_bytes())
del_esp = {f: t for f, t in registros(esp).items() if f >> 24 == 0}
print(f"\n{Path(sys.argv[1]).name}: {len(del_esp):,} registros del juego base\n")
total = 0
for ruta in sys.argv[2:]:
    dlc = memoryview(Path(ruta).read_bytes())
    cambiados = {f: t for f, t in registros(dlc).items() if f >> 24 == 0}
    choque = {f: t for f, t in cambiados.items() if f in del_esp}
    total += len(choque)
    resumen = ", ".join(f"{t} {n}" for t, n in Counter(choque.values()).most_common()) or "-"
    print(f"{Path(ruta).name:<36} modifica {len(cambiados):>6,} del juego base; {len(choque):>5,} tambien en el .esp  ({resumen})")
    for f, t in sorted(choque.items())[:15]:
        print(f"      {t} {f:08X}")
    if len(choque) > 15:
        print(f"      ... y {len(choque) - 15} mas")
print(f"\nTotal: {total:,} registros donde el .esp tapa un cambio de DLC.\n" if total else "\nNingun choque: el .esp no tapa nada de los DLC.\n")
