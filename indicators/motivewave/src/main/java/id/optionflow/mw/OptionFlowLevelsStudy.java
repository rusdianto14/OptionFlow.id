package id.optionflow.mw;

import com.motivewave.platform.sdk.common.Coordinate;
import com.motivewave.platform.sdk.common.DataContext;
import com.motivewave.platform.sdk.common.DataSeries;
import com.motivewave.platform.sdk.common.Defaults;
import com.motivewave.platform.sdk.common.Instrument;
import com.motivewave.platform.sdk.common.PathInfo;
import com.motivewave.platform.sdk.common.Settings;
import com.motivewave.platform.sdk.common.desc.BooleanDescriptor;
import com.motivewave.platform.sdk.common.desc.ColorDescriptor;
import com.motivewave.platform.sdk.common.desc.DiscreteDescriptor;
import com.motivewave.platform.sdk.common.desc.IntegerDescriptor;
import com.motivewave.platform.sdk.common.NVP;
import com.motivewave.platform.sdk.common.desc.SettingGroup;
import com.motivewave.platform.sdk.common.desc.SettingTab;
import com.motivewave.platform.sdk.common.desc.SettingsDescriptor;
import com.motivewave.platform.sdk.common.desc.StringDescriptor;
import com.motivewave.platform.sdk.draw.Line;
import com.motivewave.platform.sdk.study.RuntimeDescriptor;
import com.motivewave.platform.sdk.study.Study;
import com.motivewave.platform.sdk.study.StudyHeader;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Font;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/**
 * OptionFlow 0DTE Levels — overlay study for ES / NQ futures charts.
 *
 * Polls the OptionFlow REST API once per minute and plots:
 *   - Zero Gamma         (single line)
 *   - Call Wall          (single line)
 *   - Put Wall           (single line)
 *   - Major Long  GEX    (top N strikes, by volume)
 *   - Major Short GEX    (top N strikes, by volume)
 *
 * Levels arrive in cash-index space (SPXW / NDXP). The study reads the
 * chart's live last price as F_live, computes basis = F_live - f_synth,
 * then shifts every level into futures space (ES / NQ).
 */
@StudyHeader(
        namespace = "id.optionflow",
        id        = "OPTIONFLOW_LEVELS",
        rb        = "id.optionflow.mw.OptionFlowLevelsStudy",
        name      = "OptionFlow 0DTE Levels",
        label     = "OF Levels",
        desc      = "0DTE GEX / Zero Gamma / Walls polled from OptionFlow REST API and shifted into futures basis.",
        menu      = "OptionFlow",
        overlay   = true,
        signals   = false,
        strategy  = false,
        autoEntry = false,
        manualEntry = false,
        supportsBarUpdates = true,
        requiresBarUpdates = false,
        requiresVolume = false,
        requiresBidAskHistory = false,
        helpLink  = "https://github.com/rusdianto14/OptionFlow.id"
)
public class OptionFlowLevelsStudy extends Study {

    // ---- Setting keys ----
    private static final String S_API_URL          = "apiUrl";
    private static final String S_API_KEY          = "apiKey";
    private static final String S_UNDERLYING       = "underlying";
    private static final String S_POLL_SECONDS     = "pollSeconds";
    private static final String S_N_MAJOR          = "nMajor";

    private static final String S_SHOW_ZG          = "showZeroGamma";
    private static final String S_SHOW_WALLS       = "showWalls";
    private static final String S_SHOW_LONGS       = "showMajorLong";
    private static final String S_SHOW_SHORTS      = "showMajorShort";
    private static final String S_SHOW_LABELS      = "showLabels";
    private static final String S_SHOW_VALUES      = "showValues";

    private static final String S_COLOR_ZG         = "colorZeroGamma";
    private static final String S_COLOR_CALL_WALL  = "colorCallWall";
    private static final String S_COLOR_PUT_WALL   = "colorPutWall";
    private static final String S_COLOR_LONG       = "colorMajorLong";
    private static final String S_COLOR_SHORT      = "colorMajorShort";

    private static final String S_LINE_WIDTH       = "lineWidth";

    // ---- State ----
    private final AtomicReference<LevelsResponse> latest = new AtomicReference<>();
    private final AtomicReference<String> lastError = new AtomicReference<>();
    private ScheduledExecutorService scheduler;
    private ScheduledFuture<?> pollTask;
    private DataContext lastContext;

    @Override
    public void initialize(Defaults defaults) {
        SettingsDescriptor sd = new SettingsDescriptor();
        setSettingsDescriptor(sd);

        // ---- Tab 1: Connection ----
        SettingTab tabConn = sd.addTab("Connection");
        SettingGroup gConn = tabConn.addGroup("OptionFlow API");
        gConn.addRow(new StringDescriptor(S_API_URL, "API Base URL", "http://localhost:8000"));
        gConn.addRow(new StringDescriptor(S_API_KEY, "API Key (X-API-Key)", "changeme"));
        List<NVP> underlyings = new ArrayList<>();
        underlyings.add(new NVP("SPXW (ES futures)", "SPXW"));
        underlyings.add(new NVP("NDXP (NQ futures)", "NDXP"));
        gConn.addRow(new DiscreteDescriptor(S_UNDERLYING, "Underlying", "SPXW", underlyings));
        gConn.addRow(new IntegerDescriptor(S_POLL_SECONDS, "Poll Interval (seconds)", 60, 10, 600, 5));
        gConn.addRow(new IntegerDescriptor(S_N_MAJOR, "N major long/short", 3, 1, 5, 1));

        // ---- Tab 2: Display toggles ----
        SettingTab tabDisp = sd.addTab("Display");
        SettingGroup gDisp = tabDisp.addGroup("Visibility");
        gDisp.addRow(new BooleanDescriptor(S_SHOW_ZG,     "Show Zero Gamma",      true));
        gDisp.addRow(new BooleanDescriptor(S_SHOW_WALLS,  "Show Call/Put Walls",  true));
        gDisp.addRow(new BooleanDescriptor(S_SHOW_LONGS,  "Show Major Long GEX",  true));
        gDisp.addRow(new BooleanDescriptor(S_SHOW_SHORTS, "Show Major Short GEX", true));
        gDisp.addRow(new BooleanDescriptor(S_SHOW_LABELS, "Show level labels",    true));
        gDisp.addRow(new BooleanDescriptor(S_SHOW_VALUES, "Show numeric values",  true));
        gDisp.addRow(new IntegerDescriptor(S_LINE_WIDTH,  "Line Width (px)",      2, 1, 6, 1));

        // ---- Tab 3: Colors ----
        SettingTab tabCol = sd.addTab("Colors");
        SettingGroup gCol = tabCol.addGroup("Level Colors");
        gCol.addRow(new ColorDescriptor(S_COLOR_ZG,         "Zero Gamma",        new Color(255, 215, 0)));   // gold
        gCol.addRow(new ColorDescriptor(S_COLOR_CALL_WALL,  "Call Wall",         new Color(0, 200, 0)));      // green
        gCol.addRow(new ColorDescriptor(S_COLOR_PUT_WALL,   "Put Wall",          new Color(220, 50, 50)));    // red
        gCol.addRow(new ColorDescriptor(S_COLOR_LONG,       "Major Long GEX",    new Color(50, 180, 100)));   // teal-green
        gCol.addRow(new ColorDescriptor(S_COLOR_SHORT,      "Major Short GEX",   new Color(220, 100, 100)));  // soft red

        // Quick-settings shown next to indicator label
        sd.addQuickSettings(S_UNDERLYING, S_POLL_SECONDS, S_N_MAJOR, S_SHOW_LABELS);

        // No data series outputs; this is purely a level-drawing overlay
        RuntimeDescriptor rd = new RuntimeDescriptor();
        rd.setLabelSettings(S_UNDERLYING);
        setRuntimeDescriptor(rd);
    }

    @Override
    public void onLoad(Defaults defaults) {
        startPollingIfNeeded();
    }

    @Override
    public void onSettingsUpdated(DataContext ctx) {
        // Restart poll loop with new interval / underlying
        stopPolling();
        startPollingIfNeeded();
        // Force redraw with current snapshot if any
        repaintLevels(ctx);
    }

    @Override
    public void clearState() {
        super.clearState();
        stopPolling();
        latest.set(null);
        lastError.set(null);
    }

    @Override
    public void onBarUpdate(DataContext ctx) {
        // chart-tick driver — repaint so basis tracks live price
        lastContext = ctx;
        repaintLevels(ctx);
    }

    @Override
    public void onBarClose(DataContext ctx) {
        lastContext = ctx;
        repaintLevels(ctx);
    }

    @Override
    public void calculate(int index, DataContext ctx) {
        lastContext = ctx;
        // Only paint at the most recent bar to avoid duplicate work
        if (index == ctx.getDataSeries().size() - 1) {
            repaintLevels(ctx);
        }
    }

    // ---- Polling ----

    private synchronized void startPollingIfNeeded() {
        if (pollTask != null && !pollTask.isCancelled()) return;
        if (scheduler == null) {
            scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "optionflow-poll");
                t.setDaemon(true);
                return t;
            });
        }
        Settings s = getSettings();
        int pollSec = s == null ? 60 : s.getInteger(S_POLL_SECONDS, 60);
        pollSec = Math.max(10, pollSec);
        pollTask = scheduler.scheduleWithFixedDelay(this::pollOnce, 0, pollSec, TimeUnit.SECONDS);
    }

    private synchronized void stopPolling() {
        if (pollTask != null) {
            pollTask.cancel(true);
            pollTask = null;
        }
    }

    private void pollOnce() {
        try {
            Settings s = getSettings();
            if (s == null) return;
            String url = s.getString(S_API_URL, "");
            String key = s.getString(S_API_KEY, "");
            String und = s.getString(S_UNDERLYING, "SPXW");
            ApiClient client = new ApiClient(url, key);
            LevelsResponse r = client.fetchLevels(und);
            latest.set(r);
            lastError.set(null);
            DataContext ctx = lastContext;
            if (ctx != null) repaintLevels(ctx);
        } catch (Throwable t) {
            lastError.set(t.getMessage());
        }
    }

    // ---- Drawing ----

    private void repaintLevels(DataContext ctx) {
        if (ctx == null) return;
        LevelsResponse r = latest.get();
        if (r == null) {
            // No data yet — clear any stale figures.
            beginFigureUpdate();
            try { clearFigures(); } finally { endFigureUpdate(); }
            return;
        }

        Settings s = getSettings();
        if (s == null) return;

        DataSeries ds = ctx.getDataSeries();
        if (ds == null || ds.size() == 0) return;

        Instrument inst = ctx.getInstrument();
        double live = ds.getClose(ds.size() - 1);
        if (live <= 0 || Double.isNaN(live)) {
            return;
        }
        double basis = live - r.fSynth;

        long nowTime = ctx.getCurrentTime();
        long startTime = ds.getStartTime(0);
        if (startTime <= 0) startTime = nowTime - 24L * 3600L * 1000L;

        boolean showZG     = s.is(S_SHOW_ZG,     true);
        boolean showWalls  = s.is(S_SHOW_WALLS,  true);
        boolean showLongs  = s.is(S_SHOW_LONGS,  true);
        boolean showShorts = s.is(S_SHOW_SHORTS, true);
        boolean showLabels = s.is(S_SHOW_LABELS, true);
        boolean showValues = s.is(S_SHOW_VALUES, true);
        int width          = s.getInteger(S_LINE_WIDTH,  2);
        int nMajor         = s.getInteger(S_N_MAJOR,     3);

        Color cZG    = s.getColor(S_COLOR_ZG,        new Color(255, 215, 0));
        Color cCW    = s.getColor(S_COLOR_CALL_WALL, new Color(0, 200, 0));
        Color cPW    = s.getColor(S_COLOR_PUT_WALL,  new Color(220, 50, 50));
        Color cLong  = s.getColor(S_COLOR_LONG,      new Color(50, 180, 100));
        Color cShort = s.getColor(S_COLOR_SHORT,     new Color(220, 100, 100));

        Font font = new Font(Font.SANS_SERIF, Font.BOLD, 11);

        beginFigureUpdate();
        try {
            clearFigures();

            if (showZG && r.zeroGamma != null) {
                double y = r.zeroGamma + basis;
                addLine(startTime, nowTime, inst.round(y), cZG, width, true,
                        showLabels, "ZG", showValues ? formatPrice(inst, y) : null, font);
            }

            if (showWalls) {
                double cwY = r.callWallStrike + basis;
                double pwY = r.putWallStrike  + basis;
                addLine(startTime, nowTime, inst.round(cwY), cCW, width, true,
                        showLabels, "CW " + r.callWallOi, showValues ? formatPrice(inst, cwY) : null, font);
                addLine(startTime, nowTime, inst.round(pwY), cPW, width, true,
                        showLabels, "PW " + r.putWallOi, showValues ? formatPrice(inst, pwY) : null, font);
            }

            if (showLongs) {
                int n = Math.min(nMajor, r.majorLong.size());
                for (int i = 0; i < n; i++) {
                    LevelsResponse.MajorLevel m = r.majorLong.get(i);
                    double y = m.strike + basis;
                    addLine(startTime, nowTime, inst.round(y), cLong, width, false,
                            showLabels, "+G" + (i + 1), showValues ? formatPrice(inst, y) : null, font);
                }
            }

            if (showShorts) {
                int n = Math.min(nMajor, r.majorShort.size());
                for (int i = 0; i < n; i++) {
                    LevelsResponse.MajorLevel m = r.majorShort.get(i);
                    double y = m.strike + basis;
                    addLine(startTime, nowTime, inst.round(y), cShort, width, false,
                            showLabels, "-G" + (i + 1), showValues ? formatPrice(inst, y) : null, font);
                }
            }
        } finally {
            endFigureUpdate();
        }
    }

    private void addLine(long t0, long t1, double y, Color c, int width, boolean solid,
                         boolean showLabel, String labelText, String valueText, Font font) {
        Coordinate a = new Coordinate(t0, y);
        Coordinate b = new Coordinate(t1, y);
        PathInfo pi = new PathInfo(c, true);
        pi.setWidth(width);
        if (!solid) {
            pi.setDash(new float[] { 4f, 4f });
        }
        Line line = new Line(a, b, pi);
        line.setColor(c);
        line.setStroke(new BasicStroke(width));
        line.setExtendRightBounds(true);
        if (showLabel && labelText != null) {
            String composite = (valueText == null) ? labelText : labelText + " " + valueText;
            line.setText(composite, font);
        }
        addFigure(line);
    }

    private static String formatPrice(Instrument inst, double y) {
        if (inst != null) return inst.format(y);
        return String.format("%.2f", y);
    }
}
