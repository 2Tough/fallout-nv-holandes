# Dutch translation for FNV Wild Card (Mod Organizer 2)

The Dutch plugins on Nexus (`FalloutNV_NL.esp` and the DLC `.esp` files) are made for the
unmodded game. **FNV Wild Card** replaces thousands of the same records (YUP fixes, its own
"Fixed" copies of `FalloutNV.esm` and the DLC, new perks, restored content), so those plugins
either hide Wild Card's changes or get hidden by them.

These tools translate **your own Wild Card installation** instead:

- they read your MO2 profile and work out which copy of each plugin the game actually loads;
- they translate the text of those plugins (the vanilla text and everything the mods added);
- they write translated copies into **one new MO2 mod**, `[NL] Wild Card Nederlands`.

Nothing in the modlist is changed. Disable that mod and the game is English again.

The result cannot be shared: it contains content from hundreds of other mod authors. Every
player has to build it on their own PC. That is why this page exists instead of a download.

> The scripts and their console messages are in Spanish. The commands below are complete, so
> you do not need to read the script output to follow along. Every command prints the next
> step when it finishes.

---

## What you need

| | |
|---|---|
| FNV Wild Card | installed with Wabbajack, and the game starts |
| Windows + PowerShell | |
| Python 3.10 or newer | [python.org](https://www.python.org/downloads/); tick *Add python.exe to PATH* |
| Access to Gemini | **either** a Google Cloud project with Vertex AI (option A) **or** an AI Studio API key (option B), see below |
| Disk space | ~1 GB for the translated plugins |

You do **not** need xTranslator or FNVEdit for the text.

**Cost:** a full translation of a Wild Card profile uses about **20 USD** of Gemini (about
5 million characters: the vanilla game, the DLCs and roughly 0.5 million characters added by Wild
Card). Step 2 tells you the exact estimate for your profile before you spend anything. Every
translated string is cached, so you never pay twice for the same text. Interrupting and
restarting is free.

### Option A: Vertex AI, free with the Google Cloud trial (recommended)

New Google Cloud accounts get a **300 USD credit** for 90 days. That credit pays for Gemini on
**Vertex AI**, but **not** for AI Studio API keys. With Vertex, the text (and the optional voices
in step 8) costs you nothing.

1. Create a project at [console.cloud.google.com](https://console.cloud.google.com) and start the
   free trial (a card is needed for verification; you are not charged automatically).
2. Enable the **Vertex AI API** for the project.
3. Install the [gcloud CLI](https://cloud.google.com/sdk/docs/install) and run once:
   ```
   gcloud auth application-default login
   gcloud auth application-default set-quota-project YOUR_PROJECT_ID
   ```
4. In `config.json` (step 1): `"gemini_via": "vertex"` and `"vertex_proyecto": "YOUR_PROJECT_ID"`.
   `gemini_clave` is not used.

### Option B: AI Studio API key

Get a key at [Google AI Studio](https://aistudio.google.com/apikey) and put it in `gemini_clave`
(leave `"gemini_via": "aistudio"`). The paid tier costs about 20 USD for a full run. The free tier
costs nothing but has daily limits, so a full run takes several days (the script continues where
it stopped each day).

## 1. Set up the tools

1. Download this repository (*Code → Download ZIP*) and extract it to a short path,
   e.g. `C:\FNV_NL`. All commands below run from that folder.
2. Install the Python packages:
   ```
   cd C:\FNV_NL
   pip install -r requirements.txt
   ```
3. Copy `config.example.json` to `config.json` and fill in **one** of these:
   ```json
   "gemini_via": "vertex",
   "vertex_proyecto": "YOUR_PROJECT_ID",
   ```
   (option A), or:
   ```json
   "gemini_via": "aistudio",
   "gemini_clave": "YOUR_GEMINI_API_KEY",
   ```
   (option B). Leave the rest as it is. `gemini_modelo_dialogos` handles dialogue and quests
   (better model), and `gemini_modelo` handles everything else (cheaper). On the AI Studio free
   tier, lower `gemini_rpm` to 8.
   **Never share `config.json`:** it can contain your key.
4. Optional: edit `glosario.json`. It lists names that must not be translated (New Vegas, NCR,
   Mr. House...) and terms that must always be translated the same way.

**Close Mod Organizer 2** before running any of the commands below.

Every command needs to know where your modlist is and which profile you play. Put it in a
variable once per PowerShell window:

```
$wc = '--mo2', 'D:\Modlists\FWC', '--perfil', 'FNV Wild Card - Casual - NVR Mode'
```

Use your own modlist folder (the one with `ModOrganizer.ini`) and the exact profile name from
MO2. If you leave out `--perfil`, the profile currently selected in MO2 is used.

## 2. Count (free)

```
python wildcard_nl.py contar @wc
```

This reads every active plugin and prints how many strings each plugin has, how many characters
are new, and the estimated cost. Nothing is written.

## 3. Translate the plugins

```
python wildcard_nl.py xml @wc
python traducir_fnv.py contar   WildCard_en_de.xml
python traducir_fnv.py traducir WildCard_en_de.xml --limite 100
python traducir_fnv.py traducir WildCard_en_de.xml
```

- `xml` writes all strings to `WildCard_en_de.xml`.
- `--limite 100` is a small paid test. Check that it works before the full run.
- The full run takes a few hours. If it stops (Ctrl+C, network, daily limit), run the same
  command again and it continues where it stopped.
- Strings that failed an automatic check (broken variables, missing line breaks, the model
  answering in English) are listed in `WildCard_en_de_problemas.csv` and stay in English.
  Running `traducir` again retries them. A handful usually remain, and that is fine.

Then export the translations and copy them to the `WILDCARD` folder:

```
python traducir_fnv.py exportar-xedit WildCard_en_de.xml
mkdir WILDCARD -Force; Copy-Item traducciones_nl.txt, campos_nl.txt WILDCARD
```

## 4. Interface strings (optional, recommended)

Menus, "Take" / "Talk to", Yes/No and the wait screen are *Game Settings*. The English game
keeps most of them inside `FalloutNV.exe` rather than in a plugin. To translate them, you need a
`gmst_nl.txt`. Without it the interface stays English and everything else is still Dutch.

To make one, follow step 4 of the [main README](../README.md#4-interface-strings). It uses
FNVEdit on your normal Steam installation, not on Wild Card. Then pass the file to `construir`
with `--gmst`.

## 5. Build the Dutch mod

```
python wildcard_nl.py construir @wc --gmst C:\FNV_NL\gmst_nl.txt
```

(Leave out `--gmst` if you skipped step 4.)

This writes a translated copy of every plugin that has text into
`<modlist>\mods\[NL] Wild Card Nederlands`, with the same file names. Each copy has the same
records in the same order as the original; only the text changes. Each one is parsed again and
checked before it is saved. If a check fails, that plugin is skipped and stays English.

## 6. Scripts and Pip-Boy descriptions

Some mods write text at runtime, so it is not in any plugin:

- **xNVSE scripts** (`nvse\plugins\scripts\*.txt`): for example, PerkOut rewrites the
  descriptions of traits and perks (Hamster, Logan's Loophole...) every time a save loads.
- **B42 Descriptions / Pip-Info** (`Config\B42Descriptions\...\*.ini`): the extra item
  descriptions in the Pip-Boy.

```
python scripts_nvse_nl.py contar @wc
python scripts_nvse_nl.py xml @wc
python traducir_fnv.py traducir ScriptsNVSE_en_de.xml
python scripts_nvse_nl.py construir @wc
```

Most of these strings are already in the cache from step 3, so this costs cents. The copies go
into the same `[NL] Wild Card Nederlands` mod. Strings that could not be put back safely (format
codes such as `%g` or `%r` that do not match, or characters the game cannot display) stay English
and are listed in `ScriptsNVSE_problemas.csv`.

## 7. Enable it in MO2

1. Open MO2 and press **F5**.
2. Enable **`[NL] Wild Card Nederlands`** and drag it to the **bottom** of the left pane
   (highest priority). It must win every conflict.
3. There is nothing to activate in the right pane. The translated plugins have the same names as
   the originals and simply replace them.
4. **Do not** also enable `FalloutNV_NL.esp` or the `<DLC>_NL.esp` files from the Nexus page.

## 8. Dutch voices

The voice pack from the Nexus page works with Wild Card as it is. It is just loose `.ogg` files.

1. Install *FNV Nederlands - stemmen* in MO2 as a mod and name it exactly **`[NL] Stemmen`**.
2. Put it at the bottom of the left pane (it can sit right above or below
   `[NL] Wild Card Nederlands`).

When a Wild Card mod changed a vanilla line, that line keeps its Dutch voice but the subtitle
shows the mod's translated text. Mostly these are typo fixes.

### Optional: voices for dialogue added by mods

`voces_wildcard.py` gives Dutch voices to dialogue that mods added with English audio, using the
same voices and effects as the voice pack. It is for advanced users:

- it always uses **Vertex AI**: set it up as in option A above, even if you translated the
  text with an AI Studio key;
- it needs [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) (`ffmpeg.exe` and `ffprobe.exe` on the
  PATH or next to the scripts);
- it needs steps 3 and 5 to be done (it reads `WILDCARD\traducciones_nl.txt`).

```
python voces_wildcard.py contar @wc
python voces_wildcard.py generar @wc --limite 20 --max-dolares 1
python voces_wildcard.py generar @wc --max-dolares 10
```

`contar` is free. It prints how many lines would be voiced and what that costs, writes the full
list to `voces_wildcard_lista.csv`, and adds the voice types of new characters to
`voces_tipos.json` (check the voice and effect it picked before you generate). `generar` stops
at `--max-dolares`; run it again to continue. Output goes to the MO2 mod
`[NL] Wild Card Stemmen`. Put it **below** `[NL] Stemmen`.

Dialogue that mods added without any audio stays subtitle-only.

## After a Wild Card update

Wabbajack updates replace plugins, so the translated copies go out of date. Repeat:

```
python wildcard_nl.py xml @wc
python traducir_fnv.py traducir WildCard_en_de.xml
python traducir_fnv.py exportar-xedit WildCard_en_de.xml
Copy-Item traducciones_nl.txt, campos_nl.txt WILDCARD -Force
python wildcard_nl.py construir @wc --gmst C:\FNV_NL\gmst_nl.txt
python scripts_nvse_nl.py xml @wc
python traducir_fnv.py traducir ScriptsNVSE_en_de.xml
python scripts_nvse_nl.py construir @wc
```

Only new or changed text is paid for. The build steps also delete copies that are no longer
needed.

If you play several Wild Card profiles, run the whole thing once per profile. A plugin that only
one profile uses is only translated when that profile is selected. The cache is shared, so the
second profile is almost free.

## Uninstall

Disable `[NL] Wild Card Nederlands` (and the voice mods) in MO2. You can also delete those mod
folders. Nothing else was changed.

## What stays English

- MCM menus and text inside compiled scripts or NVSE plugins (`.dll`)
- Interface XML of UI mods (yUI and similar)
- Strings listed in the `*_problemas.csv` files
- The launcher, the intro video, and text painted into textures
- Known: during character creation, a mod adds "Ghoul:" above some trait descriptions. It is
  assembled at runtime, and "Ghoul" is the same word in Dutch anyway.

## Troubleshooting

| Problem | Fix |
|---|---|
| `No encuentro ...ModOrganizer.ini` | `--mo2` must point to the folder that contains `ModOrganizer.ini`. |
| `No encuentro el perfil ...` | Copy the profile name exactly from MO2 and keep it in quotes. |
| `No encuentro campos_nl.txt` | Run the commands from the repository folder; `campos_nl.txt` ships with it. |
| PowerShell cannot find a path with `[ ]` in it | Use `-LiteralPath` instead of `-Path` (MO2 mod names contain brackets). |
| "The process cannot access the file" | MO2 or the game is still running. Close it. |
| Some text is Dutch, some English | Check that `[NL] Wild Card Nederlands` is enabled and at the bottom, then run step 3 again to retry failed strings. |
| You want to know where an English string comes from | `python buscar_texto.py "the text" @wc` searches loose files, BSA archives, plugins and NVSE DLLs, and saves the result to `buscar_texto_resultado.txt`. |
| The game crashes after enabling the mod | Disable it to confirm. Then open an issue with your profile name and the output of `construir`. |
