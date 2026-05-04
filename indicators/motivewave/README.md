# OptionFlow MotiveWave Study

`OptionFlow 0DTE Levels` is an overlay study for MotiveWave that draws
horizontal lines on ES / NQ futures charts for the levels computed by the
[OptionFlow](https://github.com/rusdianto14/OptionFlow.id) Python engine:

| Level                | Source                                                  |
|----------------------|---------------------------------------------------------|
| **Zero Gamma**       | Brent root finder over net dealer gamma                 |
| **Call Wall**        | Strike with maximum call OI above forward               |
| **Put Wall**         | Strike with maximum put  OI below forward               |
| **Major Long GEX**   | Top N strikes with largest positive GEX (volume-weighted) |
| **Major Short GEX**  | Top N strikes with most negative GEX (volume-weighted)  |

Levels are computed in cash-index space (SPXW, NDXP). The study reads the
**live futures price** from the chart's data feed (Rithmic / CQG / etc.) and
shifts each level by

```
basis = F_live − F_synth_at_snapshot
```

so that the lines render at the correct futures price and re-anchor on every
tick.

---

## Build

Requirements:

* JDK **26+** — the MotiveWave SDK ships as Java 26 bytecode (class file v70)
* Maven 3.6+
* `mwave_sdk.jar` from MotiveWave (Help → Check For SDK / Console SDK link)

```bash
cd indicators/motivewave

# 1. Place your copy of the MotiveWave SDK here. The .gitignore excludes it
#    so we never redistribute a proprietary jar.
cp /path/to/mwave_sdk.jar lib/mwave_sdk.jar

# 2. Compile + test + package.
JAVA_HOME=/path/to/jdk-26 mvn package
```

The resulting jar is `target/optionflow-mw.jar`.

## Tests

```bash
JAVA_HOME=/path/to/jdk-26 mvn test
```

13 unit tests cover:

* `JsonParserTest`     — primitive / array / object / escape edge cases
* `LevelsResponseTest` — full SPXW snapshot round-trip, null `zero_gamma`
* `ApiClientTest`      — happy path + 401 / 404 + URL handling, run against
                         an in-process `com.sun.net.httpserver.HttpServer`

## Install in MotiveWave

1. Build the jar (see above).
2. Drop `optionflow-mw.jar` into MotiveWave's extension directory:

   * **Windows**: `%USERPROFILE%\MotiveWave Extensions\`
   * **macOS**:   `~/MotiveWave Extensions/`
   * **Linux**:   `~/MotiveWave Extensions/`

3. Restart MotiveWave.
4. Open an ES (or NQ) chart, then **Study → Add Study → OptionFlow → OptionFlow 0DTE Levels**.

## Configure

The study has three setting tabs:

### Connection

| Setting           | Default               | Notes                                      |
|-------------------|-----------------------|--------------------------------------------|
| API Base URL      | `http://localhost:8000` | Point to your OptionFlow REST API        |
| API Key           | `changeme`            | Sent as `X-API-Key` header                 |
| Underlying        | `SPXW`                | `SPXW` for ES, `NDXP` for NQ               |
| Poll Interval (s) | 60                    | Snapshots are written once per minute      |
| N major long/short| 3                     | 1–5 strikes                                |

### Display

Toggles + line width.

### Colors

Per-level color pickers. Defaults follow standard convention:

| Level           | Default color |
|-----------------|---------------|
| Zero Gamma      | gold          |
| Call Wall       | green         |
| Put Wall        | red           |
| Major Long GEX  | teal-green (dashed) |
| Major Short GEX | soft red   (dashed) |

## How it works internally

1. `initialize()` builds a `SettingsDescriptor` with three tabs.
2. `onLoad()` starts a daemon `ScheduledExecutorService` that calls
   `pollOnce()` every `pollSeconds`. Polling runs **off the chart paint
   thread** so a slow API call never freezes MotiveWave.
3. `pollOnce()` builds an `ApiClient` from the current settings, fetches
   `/levels/{underlying}`, parses it into a `LevelsResponse` POJO, and
   stashes it in an `AtomicReference`.
4. `onBarUpdate()` / `onBarClose()` / `calculate()` (whichever fires first
   for the current MotiveWave version) call `repaintLevels()`:
   * read `live = ds.getClose(last bar)`
   * `basis = live − r.f_synth`
   * `clearFigures()` then `addFigure(new Line(...))` for each enabled level
5. `onSettingsUpdated()` cancels the poll task and re-schedules with the new
   interval / underlying.
6. `clearState()` shuts everything down.

## Repo layout

```
indicators/motivewave/
├── pom.xml
├── README.md
├── lib/
│   └── mwave_sdk.jar                # MotiveWave SDK (system-scope dep)
└── src/
    ├── main/java/id/optionflow/mw/
    │   ├── OptionFlowLevelsStudy.java   # @StudyHeader entry point
    │   ├── ApiClient.java               # java.net.http wrapper
    │   ├── LevelsResponse.java          # POJO mirror of /levels JSON
    │   └── JsonParser.java              # zero-dep JSON parser
    └── test/java/id/optionflow/mw/
        ├── JsonParserTest.java
        ├── LevelsResponseTest.java
        └── ApiClientTest.java
```
