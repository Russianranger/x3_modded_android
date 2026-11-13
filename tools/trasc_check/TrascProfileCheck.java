package io.github.russianranger.trasc;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/**
 * Loads controls/generated/trasc-layers.tsv into TRASC's real ControllerInput (copied in by run.sh),
 * lets configure() apply its own validation, then drives button presses and checks the emitted keys.
 * This proves the compiled X3 profile works on the existing engine, not just in build_controls.py.
 */
public final class TrascProfileCheck {
    private static final List<String> events = new ArrayList<>();
    private static int failures;

    public static void main(String[] args) throws Exception {
        Map<Integer, String> names = new TreeMap<>();
        Map<Integer, Map<String, String>> bindings = new TreeMap<>();
        for (String line : Files.readAllLines(Paths.get(args[0]), StandardCharsets.UTF_8)) {
            if (line.isEmpty()) continue;
            String[] f = line.split("\t");
            int index = Integer.parseInt(f[0]);
            names.put(index, f[1]);
            bindings.computeIfAbsent(index, k -> new LinkedHashMap<>()).put(f[2], f[3]);
        }
        List<ControllerInput.Layer> layers = new ArrayList<>();
        for (int i : names.keySet()) layers.add(new ControllerInput.Layer(names.get(i), bindings.get(i)));

        ControllerInput input = new ControllerInput(new ControllerInput.Sink() {
            public void button(String action, boolean down) { events.add((down ? "+" : "-") + action); }
            public void pointer(float dx, float dy) {}
            public void wheel(int amount) { events.add("wheel" + amount); }
            public void layer(int index, String name) { events.add("layer:" + name); }
        });
        input.configure(layers, 0.20f, 700f);   // TRASC's own validation; throws on any invalid binding
        check("configure() accepted " + layers.size() + " layers", true);
        input.activate(true);

        tap(input, "X");
        expect("Flight X = full stop", "+Backspace", "-Backspace");

        press(input, "Select");
        check("hold Select enters System", input.layerName().equals("System"));
        tap(input, "DpadRight");
        check("still System while Select held", input.layerName().equals("System"));
        release(input, "Select");
        check("release Select lands on Navigate", input.layerName().equals("Navigate"));
        tap(input, "X");
        expect("Navigate X = SETA", "+KeyJ", "-KeyJ");
        tap(input, "Y");
        expect("Navigate Y = dock (Shift+D)", "+ShiftLeft", "+KeyD", "-KeyD", "-ShiftLeft");

        press(input, "L2");
        check("hold LT from Navigate enters Combat", input.layerName().equals("Combat"));
        tap(input, "A");
        expect("Combat A = launch missile", "+KeyL", "-KeyL");
        release(input, "L2");
        check("release LT returns to Navigate", input.layerName().equals("Navigate"));

        press(input, "Select"); tap(input, "DpadDown"); release(input, "Select");
        check("Select+Down = Menus", input.layerName().equals("Menus"));
        tap(input, "R2");
        expect("Menus RT = left click", "+MouseLeft", "-MouseLeft");

        press(input, "Select"); tap(input, "DpadLeft"); release(input, "Select");
        check("Select+Left = Command", input.layerName().equals("Command"));
        tap(input, "DpadUp");
        expect("Command D-pad up = script hotkey 1 (Shift+F5)", "+ShiftLeft", "+F5", "-F5", "-ShiftLeft");

        press(input, "Select"); tap(input, "DpadUp"); release(input, "Select");
        check("Select+Up = Flight", input.layerName().equals("Flight"));
        events.clear();
        press(input, "R2");
        press(input, "Y");
        release(input, "Y");
        release(input, "R2");
        boolean ctrlHeldDuringShiftT = events.indexOf("+ControlLeft") < events.indexOf("+KeyT")
                && events.indexOf("-ControlLeft") > events.indexOf("+KeyT");
        System.out.println("NOTE  fire held + nearest enemy sends Ctrl+Shift+T: " + ctrlHeldDuringShiftT + "  " + events);

        press(input, "Select"); press(input, "L2");
        check("Select then LT: most recent hold (Combat) wins", input.layerName().equals("Combat"));
        release(input, "L2");
        check("release LT falls back to System", input.layerName().equals("System"));
        release(input, "Select");
        check("release Select returns to Flight", input.layerName().equals("Flight"));

        press(input, "L2"); press(input, "X");
        press(input, "Select");
        boolean released = events.contains("-KeyK");
        release(input, "X"); release(input, "Select"); release(input, "L2");
        check("layer change releases held keys (no stuck K)", released);

        System.out.println(failures == 0 ? "PASS  all checks" : "FAIL  " + failures + " check(s)");
        System.exit(failures == 0 ? 0 : 1);
    }

    private static void press(ControllerInput in, String s) { in.value(s, 1f); }
    private static void release(ControllerInput in, String s) { in.value(s, 0f); }
    private static void tap(ControllerInput in, String s) { events.clear(); press(in, s); release(in, s); }

    private static void expect(String what, String... wanted) {
        List<String> keys = new ArrayList<>();
        for (String e : events) if (!e.startsWith("layer:")) keys.add(e);
        check(what + " " + keys, keys.equals(Arrays.asList(wanted)));
    }

    private static void check(String what, boolean ok) {
        System.out.println((ok ? "ok    " : "FAIL  ") + what);
        if (!ok) failures++;
    }
}
