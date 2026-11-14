package io.github.russianranger.x3;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;

/** Fails unless PeInfo.java gives the same verdict as runner/pe_info.py for every fixture. */
public final class PeInfoCheck {
    public static void main(String[] args) throws Exception {
        File dir = new File(args[0]);
        List<String> rows = Files.readAllLines(new File(dir, "expected.tsv").toPath(), StandardCharsets.UTF_8);
        int failures = 0;
        for (String expected : rows) {
            if (expected.isEmpty()) continue;
            String name = expected.split("\t", 2)[0];
            String actual;
            try {
                PeInfo.Info info = PeInfo.inspect(new File(dir, name));
                actual = String.join("\t", name, info.machine, String.valueOf(info.largeAddressAware), String.valueOf(info.gui),
                        String.valueOf(info.steamApi), String.join(",", info.imports));
            } catch (java.io.IOException e) {
                actual = name + "\tERROR";
            }
            boolean ok = actual.equals(expected);
            if (!ok) failures++;
            System.out.println((ok ? "ok    " : "FAIL  ") + actual + (ok ? "" : "\n      expected " + expected));
        }
        if (failures > 0) { System.out.println(failures + " mismatches"); System.exit(1); }
        System.out.println("PASS  Java and Python PE readers agree on " + rows.size() + " files");
    }
}
