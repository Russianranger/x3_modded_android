#!/usr/bin/env python3
"""Build every controller artifact from controls/*.json.

Inputs
  controls/x3ap-keymap.json          action id -> X3 key (single source of truth for keys)
  controls/x3ap-lxxrm.profile.json   format-3 layered profile (sources -> action ids)

Outputs (all generated, do not hand-edit)
  controls/generated/x3ap-lxxrm.trasc-v2.json   loadable by TRASC's ControllerInput (format 2)
  controls/generated/overlay-data.json          what the in-game help overlay renders
  controls/generated/v2-compat-report.md        what format 2 cannot express yet
  controls/generated/trasc-layers.tsv           input for tools/trasc_check (Java validation)
  docs/controls-cheatsheet.md                   printable per-layer tables
  overlay/layer-<n>-<name>.svg                  overlay mockups / printable cards

Usage
  python3 -I tools/build_controls.py            build
  python3 -I tools/build_controls.py --check    fail if generated files are stale
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTROLS = ROOT / "controls"
GENERATED = CONTROLS / "generated"
OVERLAY_DIR = ROOT / "overlay"
CHEATSHEET = ROOT / "docs" / "controls-cheatsheet.md"

# --- TRASC format-2 vocabulary (mirrors ControllerInput.java in trasc-server-android) ---
SOURCES = ["A", "B", "X", "Y", "L1", "R1", "L2", "R2", "L3", "R3", "Start", "Select",
           "DpadUp", "DpadDown", "DpadLeft", "DpadRight", "LeftUp", "LeftDown", "LeftLeft", "LeftRight",
           "RightUp", "RightDown", "RightLeft", "RightRight"]
MAX_LAYERS = 6


def trasc_actions():
    base = ["None", "MouseLeft", "MouseRight", "MouseMiddle", "PointerUp", "PointerDown", "PointerLeft",
            "PointerRight", "WheelUp", "WheelDown"]  # MouseLookToggle exists only for the TAKP world profile
    base += ["Key" + chr(c) for c in range(ord("A"), ord("Z") + 1)]
    base += ["Digit%d" % i for i in range(10)]
    base += ["F%d" % i for i in range(1, 13)]
    base += ["Space", "Enter", "Escape", "Tab", "Backspace", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
             "ShiftLeft", "ControlLeft", "AltLeft", "Home", "End", "PageUp", "PageDown", "Insert", "Delete",
             "Minus", "Equal", "BracketLeft", "BracketRight", "Semicolon", "Quote", "Comma", "Period", "Slash",
             "Backslash", "Backquote", "NumLock", "ClientMenu"]
    keys = list(base)
    for mod in ("ShiftLeft", "ControlLeft", "AltLeft"):
        for key in keys:
            if key.startswith("Key") or key.startswith("Digit") or re.fullmatch(r"F[0-9]+", key) or key == "Tab":
                base.append(mod + "+" + key)
    base += ["LayerNext", "LayerPrevious"]
    for i in range(1, MAX_LAYERS + 1):
        base += ["Layer%d" % i, "HoldLayer%d" % i]
    return base


TRASC_ACTIONS = set(trasc_actions())

# Keys the X3 app adds on top of TRASC (X11 keysyms exist for all of them).
EXTENDED_KEYS = {"NumpadEnter", "NumpadAdd", "NumpadSubtract", "NumpadMultiply", "NumpadDivide", "NumpadDecimal",
                 "Pause", "PrintScreen", "ScrollLock"} | {"Numpad%d" % i for i in range(10)}
MODIFIERS = {"ShiftLeft", "ControlLeft", "AltLeft"}
APP_ACTIONS = {"app.next", "app.prev", "app.help_toggle", "app.text_input", "app.client_menu", "none"}

SOURCE_DISPLAY = {"L1": "LB", "R1": "RB", "L2": "LT", "R2": "RT", "L3": "L3", "R3": "R3",
                  "DpadUp": "D-pad ↑", "DpadDown": "D-pad ↓", "DpadLeft": "D-pad ←",
                  "DpadRight": "D-pad →", "LeftUp": "LS ↑", "LeftDown": "LS ↓",
                  "LeftLeft": "LS ←", "LeftRight": "LS →", "RightUp": "RS ↑",
                  "RightDown": "RS ↓", "RightLeft": "RS ←", "RightRight": "RS →"}
ACCENTS = ["#4cc2ff", "#7ee787", "#d2a8ff", "#ffa657", "#ff7b72", "#e3b341"]

KEY_DISPLAY = {"ArrowUp": "↑", "ArrowDown": "↓", "ArrowLeft": "←", "ArrowRight": "→",
               "ShiftLeft": "Shift", "ControlLeft": "Ctrl", "AltLeft": "Alt", "PageUp": "PgUp",
               "PageDown": "PgDn", "Escape": "Esc", "Backspace": "Bksp", "Insert": "Ins", "Delete": "Del",
               "Period": ".", "Comma": ",", "Minus": "-", "Equal": "=", "Slash": "/", "Backslash": "\\",
               "Semicolon": ";", "Quote": "'", "Backquote": "`", "BracketLeft": "[", "BracketRight": "]",
               "MouseLeft": "LMB", "MouseRight": "RMB", "MouseMiddle": "MMB", "WheelUp": "Wheel ↑",
               "WheelDown": "Wheel ↓", "PointerUp": "Mouse", "PointerDown": "Mouse",
               "PointerLeft": "Mouse", "PointerRight": "Mouse", "NumpadEnter": "Num Enter",
               "NumpadAdd": "Num +", "NumpadSubtract": "Num -", "PrintScreen": "PrtSc", "Enter": "Enter"}


class BuildError(Exception):
    pass


def key_display(token):
    parts = []
    for atom in token.split("+"):
        if atom.startswith("Key") and len(atom) == 4:
            parts.append(atom[3])
        elif atom.startswith("Digit"):
            parts.append(atom[5:])
        elif atom.startswith("Numpad") and atom[6:].isdigit():
            parts.append("Num " + atom[6:])
        else:
            parts.append(KEY_DISPLAY.get(atom, atom))
    return "+".join(parts)


def valid_key_token(token):
    atoms = token.split("+")
    *mods, key = atoms
    if any(m not in MODIFIERS for m in mods) or len(set(mods)) != len(mods):
        return False
    return key in TRASC_ACTIONS or key in EXTENDED_KEYS


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError("%s: %s" % (path.relative_to(ROOT), exc))


def validate(keymap, profile):
    errors = []
    actions = keymap.get("actions", {})
    for aid, entry in actions.items():
        for field in ("label", "short", "key", "group", "status"):
            if field not in entry:
                errors.append("keymap %s: missing %s" % (aid, field))
        if "key" in entry and not valid_key_token(entry["key"]):
            errors.append("keymap %s: unknown key token %r" % (aid, entry["key"]))
        if entry.get("status") not in ("manual", "verify", "user", "app"):
            errors.append("keymap %s: bad status %r" % (aid, entry.get("status")))
    if profile.get("format") != 3:
        errors.append("profile: format must be 3")
    layers = profile.get("layers", [])
    if not 1 <= len(layers) <= MAX_LAYERS:
        errors.append("profile: 1..%d layers required (TRASC limit)" % MAX_LAYERS)
    names = [layer.get("name", "") for layer in layers]
    lowered = [n.lower() for n in names]
    if len(set(lowered)) != len(lowered):
        errors.append("profile: layer names must be unique (case-insensitive)")
    for i, layer in enumerate(layers):
        name = layer.get("name", "")
        if not name or len(name) > 24 or any(ord(c) < 32 for c in name):
            errors.append("layer %d: name must be 1-24 printable characters" % (i + 1))
        if layer.get("kind") not in ("base", "hold"):
            errors.append("layer %s: kind must be base or hold" % name)
        if i == 0 and layer.get("kind") != "base":
            errors.append("layer 1 must be a base layer")
        bindings = layer.get("bindings", {})
        unknown = set(bindings) - set(SOURCES)
        if unknown:
            errors.append("layer %s: unknown sources %s" % (name, sorted(unknown)))
        if i == 0 and set(bindings) != set(SOURCES):
            errors.append("layer 1 must bind all 24 sources; missing %s" % sorted(set(SOURCES) - set(bindings)))
        for source, value in bindings.items():
            if value in actions or value in APP_ACTIONS:
                continue
            m = re.fullmatch(r"app\.(goto|hold):(.+)", value)
            if m:
                if m.group(2).lower() not in lowered:
                    errors.append("layer %s %s: unknown layer %r" % (name, source, m.group(2)))
                continue
            errors.append("layer %s %s: unknown action %r" % (name, source, value))
        if layer.get("kind") == "hold":
            holder = layer.get("held_by")
            if holder not in SOURCES:
                errors.append("hold layer %s: held_by must be a source" % name)
            elif layers[0]["bindings"].get(holder, "").lower() != ("app.hold:" + name).lower():
                errors.append("hold layer %s: Layer 1 %s must be app.hold:%s" % (name, holder, name))
            elif holder in bindings:
                errors.append("hold layer %s: must not rebind its own button %s" % (name, holder))
    dz, sens = profile.get("deadzone"), profile.get("sensitivity")
    if not isinstance(dz, (int, float)) or not 0.05 <= dz <= 0.8:
        errors.append("deadzone must be 0.05..0.8")
    if not isinstance(sens, (int, float)) or not 50 <= sens <= 2500:
        errors.append("sensitivity must be 50..2500")
    if errors:
        raise BuildError("\n".join(errors))


def resolve(keymap, profile):
    """Return per-layer effective bindings with labels, keys and the TRASC v2 translation."""
    actions = keymap["actions"]
    layers = profile["layers"]
    index = {layer["name"].lower(): i for i, layer in enumerate(layers)}
    out, compat = [], []
    for i, layer in enumerate(layers):
        controls = []
        for source in SOURCES:
            inherited = source not in layer["bindings"]
            value = layers[0]["bindings"][source] if inherited else layer["bindings"][source]
            entry = {"source": source, "display_source": SOURCE_DISPLAY.get(source, source), "action": value,
                     "inherited": inherited, "status": "app"}
            m = re.fullmatch(r"app\.(goto|hold):(.+)", value)
            if m:
                target = index[m.group(2).lower()]
                verb = "Go to" if m.group(1) == "goto" else "Hold:"
                entry.update(label="%s %s layer" % (verb, layers[target]["name"]),
                             short=("→ " if m.group(1) == "goto" else "Hold → ") + layers[target]["name"],
                             key="", v2=("Layer%d" if m.group(1) == "goto" else "HoldLayer%d") % (target + 1))
            elif value == "app.next":
                entry.update(label="Next layer", short="Next layer", key="", v2="LayerNext")
            elif value == "app.prev":
                entry.update(label="Previous layer", short="Prev layer", key="", v2="LayerPrevious")
            elif value == "app.client_menu":
                entry.update(label="App menu (gear)", short="App menu", key="", v2="ClientMenu")
            elif value == "app.help_toggle":
                entry.update(label="Pin / unpin this help overlay", short="Pin help", key="", v2=None)
            elif value == "app.text_input":
                entry.update(label="Android keyboard (type text)", short="Keyboard", key="", v2=None)
            elif value == "none":
                entry.update(label="Unassigned", short="—", key="", v2="None")
            else:
                a = actions[value]
                entry.update(label=a["label"], short=a["short"], key=a["key"], status=a["status"],
                             v2=a["key"] if a["key"] in TRASC_ACTIONS else None)
            entry["key_display"] = key_display(entry["key"]) if entry["key"] else ""
            if entry["v2"] is None:
                if not inherited:
                    compat.append((layer["name"], source, value, entry["key"] or "(app action)"))
                entry["v2_action"] = "None"
            else:
                entry["v2_action"] = entry["v2"]
            del entry["v2"]
            controls.append(entry)
        out.append({"index": i + 1, "name": layer["name"], "kind": layer["kind"],
                    "held_by": layer.get("held_by"), "overlay": layer.get("overlay"),
                    "blurb": layer.get("blurb", ""), "accent": ACCENTS[i % len(ACCENTS)], "controls": controls})
    return out, compat


def trasc_v2(profile, resolved):
    layers = []
    for i, layer in enumerate(resolved):
        bindings = {}
        for c in layer["controls"]:
            bindings[c["source"]] = "Inherit" if (i > 0 and c["inherited"]) else c["v2_action"]
        layers.append({"name": layer["name"], "bindings": bindings})
    return {"format": 2, "layers": layers, "deadzone": profile["deadzone"], "sensitivity": profile["sensitivity"]}


def compat_report(compat):
    lines = ["# TRASC format-2 compatibility report", "",
             "Generated by `tools/build_controls.py`. These bindings cannot be expressed with the current",
             "TRASC `ControllerInput` vocabulary, so the format-2 export sets them to `None`. The X3 app's",
             "extended vocabulary (docs/04-controls.md) restores them.", "",
             "| Layer | Control | Action | Needs |", "| --- | --- | --- | --- |"]
    for layer, source, action, key in compat:
        lines.append("| %s | %s | `%s` | `%s` |" % (layer, SOURCE_DISPLAY.get(source, source), action, key))
    if not compat:
        lines.append("| — | — | — | — |")
    return "\n".join(lines) + "\n"


def cheatsheet(keymap, profile, resolved):
    used = {c["action"] for layer in resolved for c in layer["controls"]}
    lines = ["# X3 controller cheat sheet", "",
             "Generated from `controls/x3ap-lxxrm.profile.json` and `controls/x3ap-keymap.json` by",
             "`tools/build_controls.py`. Do not edit by hand.", "",
             "- **Switch base layers:** hold **Select** and press the D-pad (↑ Flight, → Navigate, ↓ Menus, ← Command).",
             "- **Help overlay:** appears while **Select** is held; **Select + Start** pins or unpins it.",
             "- **Combat:** hold **LT**. Releasing returns to the layer you were in.",
             "- *Italic* rows are inherited from Flight. `verify` = the key comes from the X3: Reunion manual and has",
             "  not yet been confirmed in Albion Prelude 3.3. `bind in X3` = you assign that key inside the game.", ""]
    for layer in resolved:
        kind = "hold %s" % SOURCE_DISPLAY.get(layer["held_by"], layer["held_by"]) if layer["kind"] == "hold" else "base"
        lines += ["## %d. %s (%s)" % (layer["index"], layer["name"], kind), "", layer["blurb"], "",
                  "| Control | Action | Key | Note |", "| --- | --- | --- | --- |"]
        for c in layer["controls"]:
            note = {"verify": "verify", "user": "bind in X3"}.get(c["status"], "")
            row = (c["display_source"], c["label"], ("`%s`" % c["key_display"]) if c["key_display"] else "", note)
            if c["inherited"]:
                row = ("*%s*" % row[0], "*%s*" % row[1], row[2], row[3])
            lines.append("| %s | %s | %s | %s |" % row)
        lines.append("")
    spare = [(aid, a) for aid, a in keymap["actions"].items() if aid not in used]
    lines += ["## Mapped in the keymap but not on the controller", "",
              "Bind these to a free control if you use them often.", "",
              "| Action | Key |", "| --- | --- |"]
    for aid, a in spare:
        lines.append("| %s | `%s` |" % (a["label"], key_display(a["key"])))
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ SVG overlay
W, H = 1280, 720
ANCHORS = {"L2": (505, 286), "L1": (528, 306), "R2": (775, 286), "R1": (752, 306),
           "Select": (612, 352), "Start": (668, 352), "LeftStick": (540, 362), "Dpad": (590, 428),
           "RightStick": (690, 428), "Y": (745, 336), "X": (721, 360), "B": (769, 360), "A": (745, 384),
           "Face": (745, 360)}
FACE_COLORS = {"A": "#3fb950", "B": "#f85149", "X": "#58a6ff", "Y": "#d29922"}


def esc(text):
    return html.escape(str(text), quote=True)


def chip(x_right, y, text, color):
    w = 7.4 * len(text) + 14
    return ('<rect x="%.1f" y="%.1f" width="%.1f" height="20" rx="5" fill="#0d141d" stroke="%s" stroke-opacity="0.55"/>'
            '<text x="%.1f" y="%.1f" font-family="DejaVu Sans Mono, monospace" font-size="12" fill="#e6edf3" '
            'text-anchor="middle">%s</text>' % (x_right - w, y - 14, w, color, x_right - w / 2, y, esc(text)))


def row_svg(x, y, width, tag, c, accent):
    opacity = "0.42" if c["inherited"] else "1"
    parts = ['<g opacity="%s">' % opacity]
    if not c["inherited"]:
        parts.append('<rect x="%d" y="%d" width="3" height="20" rx="1.5" fill="%s"/>' % (x, y - 14, accent))
    if tag in FACE_COLORS:
        parts.append('<circle cx="%d" cy="%d" r="10" fill="%s"/>' % (x + 20, y - 4, FACE_COLORS[tag]))
        parts.append('<text x="%d" y="%d" font-family="DejaVu Sans, sans-serif" font-size="12" font-weight="bold" '
                     'fill="#0b1118" text-anchor="middle">%s</text>' % (x + 20, y + 0.5, tag))
    else:
        parts.append('<text x="%d" y="%d" font-family="DejaVu Sans, sans-serif" font-size="12" fill="#8b98a8">%s</text>'
                     % (x + 10, y, esc(tag)))
    parts.append('<text x="%d" y="%d" font-family="DejaVu Sans, sans-serif" font-size="15" fill="#e6edf3">%s</text>'
                 % (x + 58, y, esc(c["short"])))
    if c["key_display"]:
        parts.append(chip(x + width - 12, y, c["key_display"], accent))
    if c["status"] == "verify":
        parts.append('<circle cx="%d" cy="%d" r="3.5" fill="#e3b341"/>' % (x + width - 4, y - 12))
    parts.append("</g>")
    return "".join(parts)


def collapse_pointer(rows):
    """Show one 'Mouse pointer' row when all four stick directions drive the pointer."""
    dirs = [c for tag, c in rows if tag in ("\u2191", "\u2193", "\u2190", "\u2192")]
    if len(dirs) == 4 and all(c["action"].startswith("input.pointer_") for c in dirs):
        merged = dict(dirs[0], short="Mouse pointer", key_display="Mouse")
        return [("move", merged)] + [(tag, c) for tag, c in rows if tag == "press"]
    return rows


def box_svg(x, y, width, title, rows, accent, anchor, side):
    rows = collapse_pointer(rows)
    h = 26 + 26 * len(rows) + (6 if title else -16)
    parts = ['<rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="#111a25" fill-opacity="0.92" stroke="#243244"/>'
             % (x, y, width, h)]
    ry = y + 22
    if title:
        parts.append('<text x="%d" y="%d" font-family="DejaVu Sans, sans-serif" font-size="11" letter-spacing="1.5" '
                     'fill="#8b98a8">%s</text>' % (x + 12, y + 18, esc(title)))
        ry = y + 46
    for tag, c in rows:
        parts.append(row_svg(x, ry, width, tag, c, accent))
        ry += 26
    ex = x + width if side == "left" else x
    ey = y + min(h / 2, 24)
    elbow = ex + (26 if side == "left" else -26)
    parts.append('<polyline points="%d,%.1f %d,%.1f %d,%d" fill="none" stroke="#3b4c61" stroke-width="1.4"/>'
                 % (ex, ey, elbow, ey, anchor[0], anchor[1]))
    parts.append('<circle cx="%d" cy="%d" r="3" fill="%s"/>' % (anchor[0], anchor[1], accent))
    return "".join(parts), h


def controller_svg(changed, accent):
    def hl(*sources):
        return accent if any(s in changed for s in sources) else "#3b4c61"
    body = ('<path d="M520 300 H760 Q820 300 835 360 L860 470 Q868 525 825 530 Q795 532 775 500 L745 455 H535 '
            'L505 500 Q485 532 455 530 Q412 525 420 470 L445 360 Q460 300 520 300 Z" fill="#161f2b" stroke="#2c3a4d" '
            'stroke-width="2"/>')
    parts = [body,
             '<rect x="485" y="276" width="44" height="14" rx="6" fill="#1b2633" stroke="%s"/>' % hl("L2"),
             '<rect x="751" y="276" width="44" height="14" rx="6" fill="#1b2633" stroke="%s"/>' % hl("R2"),
             '<rect x="500" y="296" width="60" height="8" rx="4" fill="#1b2633" stroke="%s"/>' % hl("L1"),
             '<rect x="720" y="296" width="60" height="8" rx="4" fill="#1b2633" stroke="%s"/>' % hl("R1"),
             '<circle cx="540" cy="362" r="24" fill="#0f1620" stroke="%s" stroke-width="2"/>'
             % hl("LeftUp", "LeftDown", "LeftLeft", "LeftRight", "L3"),
             '<circle cx="690" cy="428" r="24" fill="#0f1620" stroke="%s" stroke-width="2"/>'
             % hl("RightUp", "RightDown", "RightLeft", "RightRight", "R3"),
             '<path d="M582 408 h16 v12 h12 v16 h-12 v12 h-16 v-12 h-12 v-16 h12 z" fill="#0f1620" stroke="%s" '
             'stroke-width="2"/>' % hl("DpadUp", "DpadDown", "DpadLeft", "DpadRight"),
             '<rect x="602" y="346" width="20" height="12" rx="6" fill="#0f1620" stroke="%s"/>' % hl("Select"),
             '<rect x="658" y="346" width="20" height="12" rx="6" fill="#0f1620" stroke="%s"/>' % hl("Start")]
    for tag in ("A", "B", "X", "Y"):
        cx, cy = ANCHORS[tag]
        parts.append('<circle cx="%d" cy="%d" r="11" fill="%s" fill-opacity="%s" stroke="%s" stroke-width="2"/>'
                     % (cx, cy, FACE_COLORS[tag], "0.9" if tag in changed else "0.35",
                        accent if tag in changed else "none"))
        parts.append('<text x="%d" y="%d" font-family="DejaVu Sans, sans-serif" font-size="11" font-weight="bold" '
                     'fill="#0b1118" text-anchor="middle">%s</text>' % (cx, cy + 4, tag))
    return "".join(parts)


def layer_svg(resolved, layer):
    accent = layer["accent"]
    by = {c["source"]: c for c in layer["controls"]}
    changed = {c["source"] for c in layer["controls"] if not c["inherited"]} if layer["index"] > 1 else set(SOURCES)
    p = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (W, H, W, H),
         '<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0b121b"/>'
         '<stop offset="1" stop-color="#070b10"/></linearGradient></defs>',
         '<rect width="%d" height="%d" fill="url(#bg)" fill-opacity="0.94"/>' % (W, H),
         '<text x="40" y="44" font-family="DejaVu Sans, sans-serif" font-size="12" letter-spacing="2" fill="%s">'
         'LAYER %d / %d · %s</text>' % (accent, layer["index"], len(resolved),
                                            "BASE" if layer["kind"] == "base" else
                                            "HOLD " + SOURCE_DISPLAY.get(layer["held_by"], layer["held_by"]).upper()),
         '<text x="40" y="80" font-family="DejaVu Sans, sans-serif">'
         '<tspan font-size="32" font-weight="bold" fill="#e6edf3">%s</tspan>'
         '<tspan dx="20" font-size="15" fill="#8b98a8">%s</tspan></text>'
         % (esc(layer["name"]), esc(layer["blurb"]))]
    px = W - 40
    for other in reversed(resolved):
        label = other["name"]
        w = 9 * len(label) + 26
        px -= w
        active = other["index"] == layer["index"]
        p.append('<rect x="%d" y="30" width="%d" height="26" rx="13" fill="%s" fill-opacity="%s" stroke="%s"/>'
                 % (px, w, other["accent"], "0.9" if active else "0.08", other["accent"]))
        p.append('<text x="%d" y="48" font-family="DejaVu Sans, sans-serif" font-size="13" fill="%s" '
                 'text-anchor="middle">%s</text>' % (px + w / 2, "#0b1118" if active else "#c9d4df", esc(label)))
        if other["kind"] == "hold":
            p.append('<text x="%d" y="72" font-family="DejaVu Sans, sans-serif" font-size="10" fill="#8b98a8" '
                     'text-anchor="middle">hold %s</text>' % (px + w / 2, SOURCE_DISPLAY.get(other["held_by"], other["held_by"])))
        px -= 8
    p.append(controller_svg(changed, accent))
    lw, rw, lx, rx = 380, 380, 40, W - 40 - 380
    left = [("TRIGGER", [("LT", by["L2"])], ANCHORS["L2"]), ("BUMPER", [("LB", by["L1"])], ANCHORS["L1"]),
            ("", [("Select", by["Select"])], ANCHORS["Select"]),
            ("LEFT STICK", [("↑", by["LeftUp"]), ("→", by["LeftRight"]), ("↓", by["LeftDown"]),
                            ("←", by["LeftLeft"]), ("press", by["L3"])], ANCHORS["LeftStick"]),
            ("D-PAD", [("↑", by["DpadUp"]), ("→", by["DpadRight"]), ("↓", by["DpadDown"]),
                       ("←", by["DpadLeft"])], ANCHORS["Dpad"])]
    right = [("TRIGGER", [("RT", by["R2"])], ANCHORS["R2"]), ("BUMPER", [("RB", by["R1"])], ANCHORS["R1"]),
             ("", [("Start", by["Start"])], ANCHORS["Start"]),
             ("FACE BUTTONS", [("Y", by["Y"]), ("X", by["X"]), ("B", by["B"]), ("A", by["A"])], ANCHORS["Face"]),
             ("RIGHT STICK", [("↑", by["RightUp"]), ("→", by["RightRight"]), ("↓", by["RightDown"]),
                              ("←", by["RightLeft"]), ("press", by["R3"])], ANCHORS["RightStick"])]
    for column, x, width, side in ((left, lx, lw, "left"), (right, rx, rw, "right")):
        y = 100
        for title, rows, anchor in column:
            svg, h = box_svg(x, y, width, title, rows, accent, anchor, side)
            p.append(svg)
            y += h + 10
    p.append('<text x="640" y="660" font-family="DejaVu Sans, sans-serif" font-size="13" fill="#c9d4df" '
             'text-anchor="middle">Hold Select = this overlay + System layer · Select + D-pad switches layers '
             '· Select + Start pins it · Hold LT = Combat</text>')
    p.append('<text x="640" y="684" font-family="DejaVu Sans, sans-serif" font-size="12" fill="#7d8a99" '
             'text-anchor="middle">Dimmed = inherited from Flight · amber dot = key from the X3: Reunion manual, '
             'not yet confirmed in AP 3.3 · keys: controls/x3ap-keymap.json</text>')
    p.append("</svg>")
    return "\n".join(p) + "\n"


def build(check=False):
    keymap = load(CONTROLS / "x3ap-keymap.json")
    profile = load(CONTROLS / "x3ap-lxxrm.profile.json")
    validate(keymap, profile)
    resolved, compat = resolve(keymap, profile)
    v2 = trasc_v2(profile, resolved)
    for layer in v2["layers"]:
        for source, action in layer["bindings"].items():
            if action != "Inherit" and action not in TRASC_ACTIONS:
                raise BuildError("internal: v2 action %r not in TRASC vocabulary" % action)
    files = {
        GENERATED / "x3ap-lxxrm.trasc-v2.json": json.dumps(v2, indent=2, ensure_ascii=False) + "\n",
        GENERATED / "overlay-data.json": json.dumps({"format": 1, "profile": profile["name"], "layers": resolved},
                                                    indent=2, ensure_ascii=False) + "\n",
        GENERATED / "v2-compat-report.md": compat_report(compat),
        GENERATED / "trasc-layers.tsv": "".join(
            "%d\t%s\t%s\t%s\n" % (i, layer["name"], s, a)
            for i, layer in enumerate(v2["layers"]) for s, a in layer["bindings"].items()),
        CHEATSHEET: cheatsheet(keymap, profile, resolved),
    }
    for layer in resolved:
        slug = re.sub(r"[^a-z0-9]+", "-", layer["name"].lower()).strip("-")
        files[OVERLAY_DIR / ("layer-%d-%s.svg" % (layer["index"], slug))] = layer_svg(resolved, layer)
    stale = []
    for path, text in files.items():
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if stale:
        raise BuildError("stale generated files (run tools/build_controls.py):\n  " + "\n  ".join(stale))
    used = sum(1 for layer in resolved for c in layer["controls"] if not c["inherited"])
    print("ok: %d layers, %d explicit bindings, %d keymap actions, %d format-2 gaps%s"
          % (len(resolved), used, len(keymap["actions"]), len(compat), " (check)" if check else ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify generated files are current")
    args = parser.parse_args()
    try:
        build(check=args.check)
    except BuildError as exc:
        print("error: %s" % exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
