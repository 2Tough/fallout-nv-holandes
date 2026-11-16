# Fallout: New Vegas — Dutch translation pipeline (EN → NL)

A Python pipeline that machine-translates *Fallout: New Vegas* and all its DLCs into Dutch,
including the interface strings, and generates Dutch voice-over with Gemini text-to-speech. It
also has a separate tool that translates a full **FNV Wild Card** modlist on the player's own PC.

**Players:** you do not need anything from this repository. Download the finished plugins and
voices from Nexus Mods: [Fallout New Vegas Nederlands translation](https://www.nexusmods.com/newvegas/mods/100515).
**Wild Card users:** see **[docs/WILDCARD.md](docs/WILDCARD.md)**.

I built this as a personal project to learn Dutch by playing a game I know well, and as a
portfolio piece on game localization, translation APIs, binary file formats and modding. It was
developed with AI assistance; the design decisions, testing, debugging and integration are my own.

**This repository contains only tooling: no game files and no game text.**
Script names, comments and console messages are in Spanish.

## Results

| | |
|---|---|
| Base game strings exported | 71,950 lines (~3.5 M characters), 99.6 % translated |
| Written to `FalloutNV_NL.esp` | 64,622 texts in 51,541 records |
| Interface strings (Game Settings) | 1,248 translated: 1,137 added, 3 replaced |
| DLC texts | Dead Money 6,195 · Old World Blues 4,653 · Honest Hearts 3,389 · Lonesome Road 2,998 · Gun Runners' Arsenal 292 · packs 17 |
| Translation engines | DeepL (free allowance, ~950 K characters of dialogue), then Gemini only |
| Base game translation cost | < 10 USD |
| Voice-over | 29,629 base game lines with 33 Dutch voices, plus Dead Money 2,312 · Old World Blues 1,718 · Honest Hearts 1,552 · Lonesome Road 941 clips |
| Wild Card profile | 119,384 strings in the active plugins, 10,749 new beyond vanilla (~0.5 M characters, ~2 USD with a warm cache) |

## How it works

```
FalloutNV.esm / <DLC>.esm ──xTranslator──► XML (English strings)
                                               │
                                 traducir_fnv.py traducir
                 ┌─────────────────────────────┴───────────────────────────┐
     dialogue & quests (INFO/DIAL/QUST)                          everything else
     Gemini "strong" model (DeepL while it lasted)               Gemini "lite" model
                 └─────────────────────────────┬───────────────────────────┘
                          cache_traducciones.json (never pays twice)
                                               │
                                 traducir_fnv.py exportar-xedit
                                               │
                  traducciones_nl.txt + campos_nl.txt (+ gmst_nl.txt for the UI)
                                               │
                         esm_nl.py esp ──► FalloutNV_NL.esp, <DLC>_NL.esp
                                               │
        (voices) Exportar_Voces.pas → voces_fnv_vertex.py → Dutch .ogg files
```

### `traducir_fnv.py` — machine translation

- **Routing by record type and cost:** dialogue and quests go to the best model; item names
  and UI-like strings go to a cheaper one. Engines: Gemini, DeepL, Microsoft Translator, or a
  local model via Ollama.
- **Variable protection:** game variables (`<Alias=Player>`, `%s`, `%d`, `&PCName;`) and
  glossary terms are replaced by placeholders before translation and must come back exactly.
  Otherwise the string stays English and is logged to a CSV for review.
- **Quality checks for LLM output:** detects untranslated sentences, truncated or padded output,
  model chatter and reordered paragraphs. It accepts legitimate cases such as proper names, song
  titles, file paths and developer notes.
- **Batching with JSON ids:** Gemini receives batches of up to 40 strings as a JSON object and
  must return every id. Failing batches are split recursively.
- **Resumable and rate-limit aware:** every batch is cached. Per-minute limits, daily limits,
  503 overloads and quota exhaustion are handled with pauses or a clean stop.
- `exportar-xedit` accepts several XML files at once (base game + DLCs), and `buscar` tells at
  which step a string got lost.

### `esm_nl.py` — writing the translation into plugins

A reader/writer for the Fallout 3 / New Vegas plugin format: TES4 records, groups, subrecords,
`XXXX` large fields, and zlib-compressed records. No xEdit needed.

- `probar` rebuilds the whole `FalloutNV.esm` and checks that it is **byte-identical** to the
  original (465,017 records), so the reader is proven before anything is changed.
- `esp` writes an override plugin. Every dialogue topic with a translated line is copied
  **complete** (the topic and all its INFO records, translated or not) in the original order and
  with the original `PNAM`. That keeps the game from reordering lines (see below). For a DLC,
  the masters are `FalloutNV.esm` + that DLC.
- Missing Game Settings are added as new records (free FormIDs, updated `HEDR`).
- `comprobar-esp` re-reads the plugin and compares the dialogue order topic by topic.

### Voice-over — `voces_fnv.py`, `voces_fnv_vertex.py`

- `Exportar_Voces.pas` / `Exportar_Voces_DLC.pas` (FNVEdit) export every dialogue response
  with its emotion, intensity and actor notes.
- Reads the voice file list from the game's `.bsa` archives with its own BSA v104 reader, and
  matches each clip (`<quest>_<topic>_<INFO FormID>_<response>.ogg`) to its Dutch line.
- A fixed Dutch voice for every game voice type (`voces_tipos.json`). Unique characters use
  Gemini Flash TTS and generic NPCs use Flash Lite TTS. The emotion is sent as a separate style
  field so it is not read aloud.
- Automatic checks: duration against text length, and transcription of styled takes, so takes
  that read the instruction or got cut off are retried.
- ffmpeg converts to `.ogg` in the original clip's format, with loudness normalization and
  effects for robots, super mutants, ghouls and radio voices.
- Shared WAV cache, spending cap per run (`--max-dolares`), cost estimate (`contar`).
  `voces_fnv_vertex.py` runs through Vertex AI (Google Cloud credits); `voces_fnv.py` runs
  through AI Studio.
- The original `.lip` files are kept: mouths move, but not in sync.

### FNV Wild Card — `wildcard_nl.py`, `scripts_nvse_nl.py`, `voces_wildcard.py`

These read a Mod Organizer 2 profile, resolve which file of each plugin, script and voice clip
the game actually sees (overwrite > mods by priority > game folder, BSAs included), translate
them, and write translated copies into separate MO2 mods. The modlist itself is never touched.
`scripts_nvse_nl.py` also covers text that mods set at runtime through xNVSE scripts (e.g.
PerkOut's perk descriptions) and B42 Pip-Boy descriptions. Full guide: [docs/WILDCARD.md](docs/WILDCARD.md).

### Other tools

| File | Purpose |
|---|---|
| `conflictos_dlc.py` | Lists records of the DLC masters that a plugin overrides (why one base-game `.esp` hid DLC changes) |
| `buscar_bsa.py` | Searches the game's `.bsa` archives for a string |
| `buscar_texto.py` | Searches a whole MO2 modlist (loose files, BSAs, compressed plugin records, NVSE DLLs) for a string |
| `revisar_voces_vertex.py` | Copies suspicious or styled voice clips to a folder for listening, and can set them aside for regeneration |
| `aceptar_problemas.py` | Accepts reviewed lines from a `*_problemas.csv` back into the cache |
| `xedit/Exportar_GMST.pas` | Exports string Game Settings (interface texts) |
| `xedit/Exportar_Voces.pas`, `Exportar_Voces_DLC.pas` | Export dialogue responses for the voice scripts |
| `xedit/Comprobar_Orden_INFO.pas` | Compares dialogue order with and without a plugin |
| `xedit/Traduccion_NL.pas`, `Agregar_GMST.pas` | First approach (FNVEdit override plugin). Kept for reference; it has the dialogue-order issue below |

## Problems worth knowing about

**An xEdit override plugin changes the order of dialogue lines.** The first version built
`FalloutNV_NL.esp` with FNVEdit (overrides of ~51,000 records). The text looked fine, but in 338
dialogue topics the game picked lines in a different order. In the opening scene, Doc Mitchell
skipped *"Go ahead and give the vigor tester a try"*, whose end script enables the Vigor Tester,
so S.P.E.C.I.A.L. could not be assigned. xEdit shows the expected order (`INOM`) and the
resulting order (`INOA`), which made the problem measurable. Filling `PNAM` by hand,
`-FillPNAM`, or flagging the plugin as ESM did not fix it. Copying each affected topic
**complete and in its original order** (`esm_nl.py esp`) does.

**A base-game plugin hides the DLCs.** `.esp` files load after all `.esm` files, and the
base-game plugin contains records the DLCs extend (topics like GREETING, Dead Money's ALCH, Gun
Runners' Arsenal's WEAP): 384 clashes. A translated DLC `.esm` therefore does not help. The fix
is one `.esp` per DLC, with the DLC's version of those records, loaded after `FalloutNV_NL.esp`.
`conflictos_dlc.py` finds such clashes.

**The New Vegas launcher orders plugins by file date**, not by `plugins.txt`. Copying original
`.esm` files back made `FalloutNV.esm` newer than the DLCs, and the game hung in the main menu.

**Do not use xTranslator's "Finalize" on Fallout: New Vegas.** The landscape record
`LAND [00150FC0]` has a broken zlib checksum in the original file. Rewriting the `.esm` with
xTranslator broke the terrain (the player fell through the ground). The game ignores the
checksum; `esm_nl.py` decompresses it as raw deflate and copies it unchanged.

**Most interface strings are not in the English `FalloutNV.esm`.** "Take", "Talk to", Yes/No,
the main menu or "How long would you like to wait?" are Game Settings whose English defaults live
inside `FalloutNV.exe`; the English `.esm` contains only 129 of them. Localized versions ship all
of them in their `.esm`. Solution: switch the game to Spanish in Steam, export the 1,445 Game
Settings, switch back, translate them (ES → NL) and add them as new records. The game looks them
up by name, so this works on the English version.

**Mods put text where translators don't look.** In Wild Card, perks had Dutch names but English
descriptions. PerkOut rewrites them on every load from xNVSE text scripts, with values that
differ from its own `.esp`. `buscar_texto.py` was written to find such sources.

**Screen space.** "Uithoudingsvermogen" (Endurance) does not fit in the Pip-Boy and is shortened
to "Uithouding". The Vigor Tester screen is a texture with painted text, so it stays English.

**Long multi-paragraph texts:** sending line breaks as placeholders made the LLM reorder
paragraphs. Line breaks are now sent as real characters inside JSON, and the paragraph count is
checked.

**TTS reading the style aloud:** putting the emotion in the text (`[angry tone] "..."`) was
sometimes spoken. A separate style field plus transcription checks fixed it.

## Requirements

- Fallout: New Vegas (English), Windows
- Python 3.10+ and `pip install -r requirements.txt`
- A Gemini API key ([Google AI Studio](https://aistudio.google.com/apikey)); DeepL, Microsoft
  Translator and Ollama are optional
- To rebuild the vanilla plugins: [xTranslator](https://www.nexusmods.com/skyrimspecialedition/mods/134)
  (export only) and [FNVEdit / xEdit](https://github.com/TES5Edit/TES5Edit) 4.1.5 (interface strings and voice export)
- For voices: ffmpeg/ffprobe, and for Vertex AI a Google Cloud project with the gcloud CLI
  (`gcloud auth application-default login`)

## Rebuilding the vanilla translation

### 1. Export the strings

Copy the original `.esm` files next to the scripts as `FalloutNV_original.esm` and
`<DLC>_original.esm` (keep them as backups). Open each `.esm` in xTranslator (source `en`,
destination `de`: xTranslator has no Dutch option, and the label only sets code page 1252). Then
export to XML as `<name>_en_de.xml`. **Do not finalize.**

### 2. Configure

Copy `config.example.json` to `config.json` and add your key (`gemini_clave`, and the models in
`gemini_modelo` / `gemini_modelo_dialogos`). Edit `glosario.json` for terms that must not be
translated or must always be translated the same way.

### 3. Translate

```
python traducir_fnv.py contar   FalloutNV_en_de.xml              # how much text, which engine, cost
python traducir_fnv.py traducir FalloutNV_en_de.xml --limite 100 # small test
python traducir_fnv.py traducir FalloutNV_en_de.xml              # full run (resumable)
python traducir_fnv.py exportar-xedit FalloutNV_en_de.xml DeadMoney_en_de.xml ...
```

Run `traducir` again to retry the strings in `*_problemas.csv`. `exportar-xedit` writes
`traducciones_nl.txt` and `campos_nl.txt`.

### 4. Interface strings

Switch the game to Spanish in Steam. Copy `xedit/*.pas` to xEdit's `Edit Scripts` folder, load
`FalloutNV.esm`, then right-click → *Apply Script* → `Exportar_GMST`. Switch back to English and
verify the game files in Steam. Then:

```
python traducir_fnv.py gmst "<xEdit>\Edit Scripts\gmst_en.txt"     # creates gmst_nl.txt
```

### 5. Build the plugins

Put `traducciones_nl.txt`, `campos_nl.txt` and `gmst_nl.txt` in one folder (e.g. `BASE`), and
the same files **without** `gmst_nl.txt` in another (e.g. `DLC`). Without `gmst_nl.txt` in that
folder, the Game Settings are not added to every DLC plugin.

```
python esm_nl.py probar FalloutNV_original.esm                       # must say IDÉNTICO
python esm_nl.py esp    FalloutNV_original.esm FalloutNV_NL.esp BASE
python esm_nl.py comprobar-esp FalloutNV_original.esm FalloutNV_NL.esp
python esm_nl.py esp    DeadMoney_original.esm DeadMoney_NL.esp DLC  # one per DLC
```

Load order: `FalloutNV.esm` → DLC `.esm` → `FalloutNV_NL.esp` → `<DLC>_NL.esp`.

### 6. Voices (optional)

Run `Exportar_Voces` (base game) or `Exportar_Voces_DLC` in FNVEdit, then:

```
python voces_fnv_vertex.py muestras                                   # listen to the voices
python voces_fnv_vertex.py contar  "<Data>\Fallout - Voices1.bsa" "<Edit Scripts>\voces_nl.txt"
python voces_fnv_vertex.py generar "<Data>\Fallout - Voices1.bsa" "<Edit Scripts>\voces_nl.txt" --filtro vcg01 --max-dolares 1
python voces_fnv_vertex.py generar "<Data>\DeadMoney - Main.bsa" "<Edit Scripts>\voces_nl_DeadMoney.txt" --max-dolares 10
```

Copy `salida_voces\sound` into `Data` and enable archive invalidation
(`bInvalidateOlderFiles=1` and `SInvalidationFile=` under `[Archive]` in `Fallout.ini`).

## Limitations

- Machine translation: generally good but not proofread. Some idioms and context-dependent lines
  are off.
- The launcher, the intro video and text painted into textures stay English.
- Lip-sync is not regenerated.
- Wild Card output cannot be redistributed: it contains other authors' content.

## License

Code: MIT (see `LICENSE`). Fallout: New Vegas is © Bethesda Softworks / ZeniMax Media.
This repository contains no game files or game text.
