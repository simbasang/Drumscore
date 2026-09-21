# Drumscore — nulägesbeskrivning (2026-09-20)

Detta är underlaget för nästa projektplan. Det beskriver hur appen faktiskt
fungerar just nu (inte hur PROJECT.md ursprungligen tänkte sig det), vilka
buggar som är fixade, vilka som är kända och öppna, och varför vissa
designval blev som de blev. Skrivet efter en fullständig genomläsning av
koden (inte bara commit-historiken), så avvikelser från PROJECT.md/spec är
markerade explicit.

Referenser: `PROJECT.md` (ursprunglig spec), `TECHNICAL_DEBT.md` (löpande
teknisk skuld-logg), `README.md` (körinstruktioner).

---

## 1. Teknikstack (faktisk, inte bara "föreslagen")

**Frontend:** Next.js (App Router, TypeScript), React, VexFlow 4/5 (SVG-
rendering av notation), Web Audio API (rå, inga wrapper-bibliotek). Testat
med Jest + React Testing Library (87 tester, 11 test-suites).

**Backend:** Python 3.13, FastAPI, körs via `uv`. Jobb körs som
bakgrundstasks i samma process (`BackgroundTasks`), begränsat till 2
samtidiga pipelines via en `threading.BoundedSemaphore`
(`PipelineConcurrencyLimiter` i `job_processor.py`) — ingen extern kö
(Celery/Redis/etc). 116 pytest-tester.

**Ljudextraktion:** `yt-dlp` + ffmpeg, bakom ett `AudioExtractor`-interface
(`youtube_audio_extractor.py`).

**Stemseparation:** Demucs (`htdemucs`-modellen), bakom ett
`StemSeparator`-interface (`demucs_stem_separator.py`). Producerar
`drums.wav` och `no_drums.wav`, 16-bit PCM stereo 44.1kHz.

**Trumtranskribering:** **DrumScript** — ett externt, regelbaserat
(icke-ML) klassificeringsverktyg som körs som en subprocess i en **separat
Python 3.12-venv** (`backend/drumscript_runner/`), eftersom DrumScript
kräver Python <3.13 och huvudbackend kör 3.13. Anropas via
`subprocess.run(...)`, timeout 600s, kommunicerar via en JSON-fil
(`events.json`) som skrivs till en temp-katalog. Resultatet mappas om till
appens egna `DrumEvent`-objekt bakom `DrumTranscriber`-interfacet
(`drumscript_transcriber.py`).

**Temoupattning:** `librosa.beat.beat_track` + en egen oktavfels-korrigering
(`librosa_tempo_estimator.py`) — se avsnitt 4.

---

## 2. Dataflöde end-to-end (så som det faktiskt är kopplat idag)

```
YouTube-URL
  → yt-dlp extraherar källjud (source.wav)
  → Demucs separerar käll-ljudet i drums.wav + no_drums.wav
  → DrumScript (subprocess, egen venv) transkriberar drums.wav
    → rådata mappas till DrumEvent[9 instrumenttyper], varje event har
      bara { id, time } ifyllt — velocity/confidence sätts ALDRIG
      (finns i datamodellen men lämnas None/null hela vägen)
  → librosa uppskattar EN enda global BPM för hela låten
  → quantize_events() rundar varje events tid till närmaste 16:e-dels-
    position på ett KONSTANT-tempo-rutnät ankrat vid t=0
    (ingen fasjustering mot faktisk taktslag-1-position)
  → jobbet markeras "tempo_mapped" (= "Done" i UI:t) med
    { tempo_bpm: <ett flyttal>, events: [...med measure/beat/subdivision] }
  → frontend hämtar /analysis (events + tempoBpm) och de två ljudfilerna
  → DrumScore.tsx bygger noter från measure/beat/subdivision (inte från
    events[].time) och renderar med VexFlow
  → Player.tsx/SyncedPlayer.ts spelar upp de två stereo-wav-filerna
    synkront via Web Audio API, currentTime läses varje rAF-tick från
    AudioContext.currentTime (ej egen klocka)
```

**Viktig avvikelse från PROJECT.md §5:** specen ville ha en riktig
`tempoMap: TempoPoint[]` (flera tempopunkter över tid, för att hantera
temposvängningar). Det som faktiskt byggdes är **ett enda skalärt BPM-tal
per låt** (`job.tempo_bpm: float`), använt både för kvantisering på
backend och för att räkna ut notpositioner (playhead-x) på frontend. Det
här är den troliga huvudorsaken till flera av dagens problem — se avsnitt
5 och 6.

---

## 3. Notation — hur den faktiskt byggs och renderas

- `buildScore.ts`: delar varje takt i **exakt 16 sexton­dels-positioner**
  (`BEATS_PER_MEASURE=4 × SUBDIVISIONS_PER_BEAT=4`). Varje position blir
  antingen en not (om något `DrumEvent` kvantiserades dit) eller en paus.
- Pauser konsolideras (`consolidateRests`) till större pausvärden (en tom
  takt → en helnotspaus istället för 16 sextondelspauser) — det här är
  löst (MVP-011).
- **Noter konsolideras aldrig.** Varje träff renderas alltid som en
  sextondelsnot (`duration: "16"` hårdkodat i `buildNoteSpec`), oavsett om
  det faktiska mönstret musikaliskt är fjärdedelar eller åttondelar. Det
  finns ingen motsvarighet till pauskonsolideringen för toner. Det här är
  en trolig delorsak till att notbilden ser tätare/stökigare ut än dina
  referensbilder, som använder fjärdedels-/åttondelsnoteringar där
  rytmiken faktiskt är glesare.
- `buildStaveNote.ts` sätter `stemDirection: 1, autoStem: false` explicit
  på varje not → **alla stammar pekar redan uppåt**, per krav. Detta är
  implementerat korrekt och testat.
- `INSTRUMENT_NOTATION` (instrumentNotation.ts) mappar varje instrument
  till en VexFlow-notehead-position på en **standard percussion-clef**,
  vilket VexFlow ritar som en vanlig 5-linjers stav (`addClef("percussion")`
  på första kolumnen i varje rad). Så strukturellt *är* det redan en
  5-linjers stav — det som troligen upplevs som "fel" är densiteten/
  röran, inte antalet linjer.
- Layout: fast `MEASURES_PER_ROW = 4`, `MEASURE_WIDTH = 200px`, ingen
  dynamisk radbrytning baserat på notinnehåll.
- Öppen/stängd hi-hat: samma notehead (`g/5/x2`), särskiljs bara via en
  VexFlow-artikulation (`"ah"` = open) ovanför noten — det är den
  standardmetod VexFlow stödjer, men **inte samma visuella markering som
  din referensbild** (som använder en ring/cirkel runt noten, dvs en
  annan notehead-variant). Kan vara en bidragande orsak till att många
  toner i din genererade bild verkar ha en liten cirkel ovanför sig —
  det är "open hi-hat"-artikulationen som troligen triggas alldeles för
  ofta (se avsnitt 5, transkriberingskvalitet).

---

## 4. Temopuppskattning och kvantisering — kända begränsningar

- `LibrosaTempoEstimator` ger **ett enda BPM-tal**, inte en tempokurva.
  Har en egen oktavfels-korrigering (väljer bästa av tempo, tempo×2,
  tempo/2 baserat på hur väl onset-tider passar rutnätet), men korrigerar
  **inte** 1.5×-typen av fel (enkel vs. sammansatt taktart-förväxling) —
  dokumenterat känt kvarstående problem i `TECHNICAL_DEBT.md`
  ("Tempo estimation disagrees with DrumScript's own estimate": 123 vs.
  184.6 BPM på ett testspår, en 1.5× "pulse-level"-ambiguitet).
- **Ingen fasjustering / downbeat-detektion.** `quantize_events()` antar
  att takt 1, slag 1 börjar exakt vid `event.time = 0` (låtens start).
  Om låtens faktiska första trumslag inte ligger exakt på t=0 (vilket det
  nästan aldrig gör — det finns nästan alltid en upptakt eller tystnad
  innan första slaget), blir **hela rutnätet fasförskjutet**, och även en
  perfekt spelad, metronom-exakt trumloop kvantiseras fel eftersom
  rutnätet i sig inte är i fas med musiken. Det här är inte dokumenterat
  i TECHNICAL_DEBT.md ännu — det är en ny observation från den här
  genomläsningen och en stark kandidat till varför notbilden "inte håller
  strukturen av 4/4" trots att låten sannolikt faktiskt är i 4/4.
- Kombinationen (fel BPM och/eller fel fas + inget konsolideringssteg för
  noter + möjlig över-detektering från DrumScript) är den mest sannolika
  förklaringen till skärmdump #4: ett tätt, orytmiskt nätverk av
  sextondelar snarare än en läsbar groove.

---

## 5. Transkriberingskvalitet (DrumScript)

Redan dokumenterat i `TECHNICAL_DEBT.md` ("Generated notation doesn't
look/read quite right yet", del 2): DrumScript är regelbaserad (inte ML)
och enligt sin egen dokumentation svagast utanför snabba/metal-genrer.
Det här är en **fundamental begränsning i det valda verktyget**, inte en
bugg vi kan snabbfixa. Alternativ som noterats men inte gjorts:
tröskeljustering mot märkt data, byta/blanda transkriberingsmotor bakom
`DrumTranscriber`-interfacet, eller en manuell korrigerings-UI (redan på
post-MVP-roadmapen i PROJECT.md §16).

`velocity`/`confidence` sätts aldrig av `_map_events()` i
`drumscript_transcriber.py`, trots att `DrumEvent`-modellen har fälten.
Det gör t.ex. en framtida "confidence-driven correction UI" (roadmap-punkt
10) omöjlig utan att först koppla på riktig confidence-data.

---

## 6. Uppspelning och synkronisering (Player / SyncedPlayer)

**Arkitekturen här är korrekt byggd enligt PROJECT.md:s princip** —
`SyncedPlayer.getCurrentTime()` härleder alltid tiden från
`AudioContext.currentTime` (den faktiska ljud-klockan), aldrig från en
egen timer. `requestAnimationFrame` används bara för att trigga
UI-omritning, inte som tidskälla. Play/pause/seek/volym är implementerade
och testade (SyncedPlayer.test.ts). Detta är redan löst korrekt och
troligen INTE källan till "markören hoppar fram och tillbaka".

**Den troliga källan** ligger istället i hur notationen räknar ut VAR på
skärmen (vilket x, vilken rad) markören ska stå för en given tidpunkt:

- `DrumScore.tsx` bygger, en gång per notrendering, en lista
  `TimelinePoint[]` — en punkt per notslot (även pauser), där varje punkts
  `time` räknas ut av `computeSlotTimeSeconds(measure, beat, subdivision,
  tempoBpm, ...)`, dvs **återigen ett konstant-tempo-antagande**, helt
  frikopplat från de verkliga ljud-tidsstämplarna (`event.time`) som kom
  från transkriberingen. Det är alltså den KVANTISERADE, rutnäts-baserade
  tiden som används för att placera markören horisontellt — inte den
  ursprungliga ljud-tidsstämpeln.
- Varje `requestAnimationFrame`-tick ger den RIKTIGA ljud-tiden från
  `SyncedPlayer` till `DrumScore` via `currentTime`-propen, som sedan via
  `interpolatePlayheadX()` letar upp var i den konstant-tempo-baserade
  `TimelinePoint[]`-listan den tiden "borde" hamna.
- Om låtens verkliga tempo inte är perfekt konstant (vilket det nästan
  aldrig är i en riktig inspelning), eller om rutnätet är fasförskjutet
  (se avsnitt 4), driver den riktiga ljud-tiden och den
  rutnäts-approximerade tiden isär ju längre låten spelas — markören kan
  då hamna på fel takt/slag för den faktiska ljudpositionen, vilket kan
  upplevas som att den "hoppar" eller inte rör sig jämnt, särskilt kring
  radbrytningar (`row`) där ett litet tidsfel ger ett stort visuellt
  hopp i x/y.
- **Detta är en trolig men inte bekräftad orsak** — jag har läst koden
  men inte gjort en live-repro med instrumentering ännu (det är nästa
  steg om vi går vidare med systematic-debugging på just den här buggen).
  En annan möjlig bidragande faktor jag inte kunnat utesluta utan repro:
  om `events`-proppen som skickas ner till `DrumScore` inte har en stabil
  referens mellan renderingar skulle hela notbilden (och därmed
  `timelineRef`) byggas om ideligen under uppspelning — det skulle också
  se ut som att markören "hoppar". Behöver verifieras i browser, inte
  bara läsas ur koden.

---

## 7. Ny bugg: `AbortError: The operation was aborted.`

Sett i Next.js dev-overlayn vid senaste manuella testet. **Grep genom hela
frontend-koden visar noll användningar av `AbortController`/`AbortSignal`
någonstans** — appen skickar aldrig själv en abort-signal till en fetch.
Det betyder att felet troligen kommer från webbläsaren/Next.js-dev-miljön
själv (t.ex. Turbopack Fast Refresh/HMR som avbryter en pågående nätverks-
request när filer ändras, eller sidnavigering medan en av de två ~45MB
ljud-fetcharna fortfarande laddar) snarare än från vår egen kod. **Inte
bekräftad** — behöver fullständig stacktrace/repro-steg (var i flödet,
vad gjorde du precis innan, F12-konsolens fulla loggar) för att fastställa
om det är ett verkligt produktionsproblem eller ett dev-only Turbopack-
artefakt.

---

## 8. Kända buggar — FIXADE (kronologisk, från TECHNICAL_DEBT.md + denna
   sessions arbete)

Alla nedan är verifierat lösta med tester, se `TECHNICAL_DEBT.md` för
fullständiga detaljer per post:

1. **Disk cleanup** — gamla jobbfiler städas nu bort efter 24h
   (`job_cleanup.py`).
2. **Ingen concurrency-gräns** — `PipelineConcurrencyLimiter` begränsar nu
   till 2 samtidiga pipelines.
3. **Ingen retry för misslyckade pipeline-steg** — `POST
   /api/jobs/{id}/retry` finns nu, återupptar från senaste lyckade steg.
4. **Oktavfel i tempouppskattning** — delvis löst (tempo/2/tempo×2-
   korrigering), men INTE 1.5×-fallet (se avsnitt 4).
5. **Ej konsoliderade pauser** — löst (`consolidateRests`), se avsnitt 3.
6. **Ingen auto-scroll** — horisontell auto-scroll löst
   (`computeAutoScrollLeft`); vertikal auto-scroll inte relevant ännu
   (containern har ingen begränsad höjd).
7. **AudioContext läckte mellan jobb** — löst, `Player` stänger nu sin
   context vid unmount.
8. **Uppspelning stannade/nollställdes inte vid låtens slut** — löst,
   `SyncedPlayer` klipper nu tiden och stoppar korrekt vid `duration`.
9. **Enstaka nätverksfel stoppade jobb-polling permanent** — löst,
   tolererar nu 2 på varandra följande fel innan den ger upp.
10. **(Denna sessions PR #27, redan mergad till main)** —
    `loadAudioBuffer` saknade retries/loggning och `Player.tsx` svalde
    det riktiga felet i en tom `catch {}`, vilket gjorde
    "Failed to load audio for playback"-felet odiagnostiserbart. Nu:
    3 försök med exponential backoff (300ms/600ms) + loggning i frontend,
    plus att backend nu faktiskt har loggkonfiguration (den hade INGEN
    tidigare — `logger.info`-anrop försvann tyst under `uvicorn --reload`).
    Bekräftat under detta arbete: backend serverar båda ljudfilerna
    korrekt (200 OK, giltig 16-bit PCM WAV) — felet i den ursprungliga
    rapporten var alltså transient/miljörelaterat, inte en permanent
    server-bugg.

---

## 9. Kända buggar/begränsningar — ÖPPNA (prioritetsordning föreslås i
   nästa steg, inte här)

1. **Notationen ser stökig/orytmisk ut, matchar inte referensstilen**
   (dagens rapport). Trolig rotorsak: kombinationen av (a) inget
   fasjusterat rutnät vid kvantisering (avsnitt 4), (b) inget
   not-konsolideringssteg motsvarande pauskonsolideringen (avsnitt 3),
   och (c) möjlig över-detektering/felklassificering från DrumScript
   (avsnitt 5) — särskilt om "open hi-hat" verkar triggas onaturligt
   ofta.
2. **Markören hoppar fram och tillbaka under uppspelning** (dagens
   rapport). Trolig rotorsak: `DrumScore.tsx` placerar markören baserat
   på ett konstant-tempo-antagande (`computeSlotTimeSeconds`) som är
   frikopplat från den riktiga ljud-tiden `SyncedPlayer` levererar —
   se avsnitt 6. Ej bekräftad med live-repro än.
3. **`AbortError: The operation was aborted.`** (dagens rapport). Ej
   bekräftad, ingen `AbortController` i vår egen kod — se avsnitt 7.
4. **Tempo-oenighet vid 1.5×-fel** (kvarstår delvis, se avsnitt 4/8.4).
5. **Klassificeringsnoggrannhet** — fundamental DrumScript-begränsning,
   inget snabbfix (avsnitt 5).
6. **`velocity`/`confidence` populeras aldrig** — blockerar framtida
   confidence-driven correction UI (roadmap-punkt 10 i PROJECT.md).
7. **Ingen vertikal auto-scroll** — inte relevant ännu (ingen begränsad
   containerhöjd), men blir det om notbilden någonsin får en fast höjd.
8. **Öppen hi-hat markeras med VexFlow-artikulation, inte cirkel-notehead**
   — avviker visuellt från din referensbild (avsnitt 3).
9. Från förra sessionens slutgranskning, medvetet nedprioriterat/
   avgränsat (se `docs/superpowers/plans/2026-09-18-...md` för detaljer):
   job-polling (`frontend/lib/api/jobs.ts`) saknar samma
   retry/loggnings-förbättring som ljuduppspelningen fick — samma typ av
   transient-fel-exponering kan uppstå där också.

---

## 10. Designval och varför (utöver det som redan står i PROJECT.md §17)

- **Enda-BPM istället för TempoPoint[]-tempokarta:** förenkling gjord
  under implementationen (dokumenterad avvikelse, inte i
  TECHNICAL_DEBT.md tidigare). Enklare att implementera och testa i
  MVP-fasen, men är den arkitektoniska roten till flera av dagens
  problem — se avsnitt 4 och 6. Kvantiseringen sker fortfarande utan att
  radera `event.time` (originaltiden finns kvar i modellen, bara inte
  synlig i notationslagret) — så PROJECT.md:s hårdaste regel ("audio
  timestamps are the source of truth", §17.1) är formellt inte bruten
  på datamodellnivå, men *används* inte konsekvent i
  presentationslagret, vilket är precis det PROJECT.md §4 varnade för.
- **DrumScript vald framför att bygga egen ML-modell:** motiverat i
  MVP-005:s utvärderingsanteckningar (se git-historik) — regelbaserad,
  snabb att integrera, "good enough" som startpunkt, bakom ett utbytbart
  interface (`DrumTranscriber`) enligt PROJECT.md §3.4:s krav. Kostnaden
  är den kända noggrannhetsbegränsningen (avsnitt 5).
- **In-process bakgrundsjobb istället för extern kö:** medvetet MVP-val
  enligt PROJECT.md §11 ("a simple in-process/background job
  implementation is acceptable"). Arkitekturen (interface-baserad
  `run_pipeline`) tillåter en riktig kö senare utan omskrivning.
- **Stems forced upward via `stemDirection`/`autoStem: false`, inte
  VexFlow-standard:** direkt krav i PROJECT.md §6, implementerat
  explicit i `buildStaveNote.ts` istället för att lita på
  VexFlow-defaults — korrekt enligt spec.
- **Web Audio API rakt av, inget wrapper-bibliotek:** matchar
  PROJECT.md §8/§9:s krav på att ljud-klockan (inte en separat timer) styr
  uppspelningspositionen, och ger full kontroll över gain-noder för
  drum-volymmixern.

---

## 11. Vad som INTE är utrett ännu (kräver repro/instrumentering, inte
    bara kodläsning)

- Exakt varför markören "hoppar" — hypotesen i avsnitt 6 är kodbaserad,
  inte verifierad i en körande browser.
- `AbortError`:ns exakta ursprung — behöver full stacktrace.
- Om DrumScripts över-detektering av öppen hi-hat är verklig eller om det
  är kvantiseringsfelet som gör att många legitima hi-hat-träffar hamnar
  på fel plats och därmed ser ut som brus.
- Hur mycket av "stökigheten" i skärmdump #4 som beror på notationslagret
  (fasfel, ingen notkonsolidering) kontra hur mycket som beror på faktiska
  felklassificeringar i DrumScripts output — dessa två går inte att skilja
  åt utan att logga/inspektera de rå kvantiserade eventen mot den rå
  DrumScript-outputen för samma låt.
