package io.github.russianranger.x3;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Drives the X3 app's ControllerInput + DisplayInput with the generated X3 profile. */
public final class X3ControllerCheck {
    private static final List<String> events = new ArrayList<>();
    private static final List<Integer> keysyms = new ArrayList<>();
    private static int failures;

    public static void main(String[] args) throws Exception {
        Map<Integer, String> names = new TreeMap<>();
        Map<Integer, Map<String, String>> bindings = new TreeMap<>();
        for (String line : Files.readAllLines(Paths.get(args[0]), StandardCharsets.UTF_8)) {
            if (line.isEmpty()) continue;
            String[] f = line.split("\t");
            names.put(Integer.parseInt(f[0]), f[1]);
            bindings.computeIfAbsent(Integer.parseInt(f[0]), k -> new LinkedHashMap<>()).put(f[2], f[3]);
        }
        List<ControllerInput.Layer> layers = new ArrayList<>();
        for (int i : names.keySet()) layers.add(new ControllerInput.Layer(names.get(i), bindings.get(i)));
        DisplayInput display = new DisplayInput(new DisplayInput.Sink() {
            public void key(int symbol, boolean down) { if (down) keysyms.add(symbol); }
            public void pointer(int x, int y, int buttons) {}
        });
        ControllerInput input = new ControllerInput(new ControllerInput.Sink() {
            public void button(String action, boolean down) {
                events.add((down ? "+" : "-") + action);
                if (!ControllerInput.APP_ACTIONS.contains(action)) display.action(action, down);
            }
            public void pointer(float dx, float dy) {}
            public void wheel(int amount) {}
            public void layer(int index, String name) { events.add("layer:" + name); }
        });
        input.configure(layers, 0.20f, 700f);
        check("configure() accepted " + layers.size() + " layers with the extended vocabulary", true);
        input.activate(true);

        tap(input, "Start");
        check("Flight Start sends Num Enter keysym 0xff8d " + keysyms, keysyms.equals(List.of(0xff8d)));

        input.value("Select", 1f);
        tap(input, "Start");
        check("Select+Start emits HelpOverlayToggle once " + events, events.equals(List.of("+HelpOverlayToggle")));
        tap(input, "Y");
        check("Select+Y emits TextInput " + events, events.equals(List.of("+TextInput")));
        tap(input, "A");
        check("Select+A sends Pause keysym 0xff13 " + keysyms, keysyms.equals(List.of(0xff13)));
        input.value("Select", 0f);
        check("release Select returns to Flight", input.layerName().equals("Flight"));

        tap(input, "Y");
        check("Flight Y sends Shift then t (uppercase T keysym) " + keysyms, keysyms.equals(List.of(0xffe1, (int) 'T')));

        System.out.println(failures == 0 ? "PASS  all checks" : "FAIL  " + failures + " check(s)");
        System.exit(failures == 0 ? 0 : 1);
    }

    private static void tap(ControllerInput in, String s) { events.clear(); keysyms.clear(); in.value(s, 1f); in.value(s, 0f); }

    private static void check(String what, boolean ok) {
        System.out.println((ok ? "ok    " : "FAIL  ") + what);
        if (!ok) failures++;
    }
}
