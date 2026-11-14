// Adapted from trasc-server-android ControllerInput.java (commit 99e8c86f).
// X3 changes: EverQuest presets removed (the default profile is the generated
// assets/controls/x3app-controller.json); extended vocabulary (numpad, Pause, PrintScreen) and
// app actions HelpOverlayToggle / TextInput; MouseLookToggle (TAKP-only) dropped. Layer logic,
// inheritance, held overrides and output reference counting are unchanged.
package io.github.russianranger.x3;

import java.util.*;

/** Platform-independent input state. */
final class ControllerInput {
    interface Sink {void button(String action,boolean down);void pointer(float dx,float dy);void wheel(int amount);default void layer(int index,String name){}}
    static final int MAX_LAYERS=6;
    static final class Layer {
        final String name;final Map<String,String> bindings;
        Layer(String name,Map<String,String> bindings){this.name=name;this.bindings=Collections.unmodifiableMap(new LinkedHashMap<>(bindings));}
    }
    static final List<String> SOURCES=Collections.unmodifiableList(Arrays.asList(
        "A","B","X","Y","L1","R1","L2","R2","L3","R3","Start","Select",
        "DpadUp","DpadDown","DpadLeft","DpadRight","LeftUp","LeftDown","LeftLeft","LeftRight",
        "RightUp","RightDown","RightLeft","RightRight"));
    /** Actions handled by the app, never sent to the game as keys. Delivered once, on press. */
    static final Set<String> APP_ACTIONS=Collections.unmodifiableSet(new HashSet<>(Arrays.asList("ClientMenu","HelpOverlayToggle","TextInput")));
    static final List<String> EXTENDED_KEYS;
    static final List<String> ACTIONS;
    static {
        List<String> extended=new ArrayList<>(Arrays.asList("NumpadEnter","NumpadAdd","NumpadSubtract","NumpadMultiply","NumpadDivide","NumpadDecimal","Pause","PrintScreen","ScrollLock"));
        for(int i=0;i<=9;i++)extended.add("Numpad"+i);
        EXTENDED_KEYS=Collections.unmodifiableList(extended);
        List<String> list=new ArrayList<>(Arrays.asList("None","MouseLeft","MouseRight","MouseMiddle","PointerUp","PointerDown","PointerLeft","PointerRight","WheelUp","WheelDown"));
        for(char c='A';c<='Z';c++)list.add("Key"+c);
        for(int i=0;i<=9;i++)list.add("Digit"+i);
        for(int i=1;i<=12;i++)list.add("F"+i);
        list.addAll(Arrays.asList("Space","Enter","Escape","Tab","Backspace","ArrowUp","ArrowDown","ArrowLeft","ArrowRight","ShiftLeft","ControlLeft","AltLeft","Home","End","PageUp","PageDown","Insert","Delete","Minus","Equal","BracketLeft","BracketRight","Semicolon","Quote","Comma","Period","Slash","Backslash","Backquote","NumLock"));
        list.addAll(extended);
        List<String> keys=new ArrayList<>(list);
        for(String mod:Arrays.asList("ShiftLeft","ControlLeft","AltLeft"))
            for(String key:keys)if(key.startsWith("Key")||key.startsWith("Digit")||key.matches("F[0-9]+")||key.equals("Tab")||key.startsWith("Numpad"))list.add(mod+"+"+key);
        list.addAll(APP_ACTIONS);
        list.addAll(Arrays.asList("LayerNext","LayerPrevious"));
        for(int i=1;i<=MAX_LAYERS;i++){list.add("Layer"+i);list.add("HoldLayer"+i);}
        ACTIONS=Collections.unmodifiableList(list);
    }
    static Map<String,String> legacyDefaults() {
        Map<String,String> m=new LinkedHashMap<>();for(String s:SOURCES)m.put(s,"None");
        m.put("A","Enter");m.put("B","Escape");m.put("X","Backspace");m.put("Y","ShiftLeft+KeyT");
        m.put("L1","PageDown");m.put("R1","PageUp");m.put("L2","MouseRight");m.put("R2","ControlLeft");
        m.put("Start","ClientMenu");m.put("Select","HelpOverlayToggle");
        for(String dir:Arrays.asList("Up","Down","Left","Right")){m.put("Left"+dir,"Arrow"+dir);m.put("Right"+dir,"Pointer"+dir);}
        m.put("DpadUp","KeyX");m.put("DpadDown","KeyZ");m.put("DpadLeft","KeyQ");m.put("DpadRight","KeyE");
        return m;
    }
    static Map<String,String> inherited(){Map<String,String> m=new LinkedHashMap<>();for(String s:SOURCES)m.put(s,"Inherit");return m;}
    /** Fallback only; ControllerManager normally loads the generated X3 profile. */
    static List<Layer> defaultLayers(){return Collections.singletonList(new Layer("Flight",legacyDefaults()));}
    static boolean isLayerAction(String action){return action.startsWith("Layer")||action.startsWith("HoldLayer");}
    static int layerTarget(String action){
        if(action.matches("(?:HoldLayer|Layer)[1-6]"))return Integer.parseInt(action.substring(action.length()-1))-1;
        return -1;
    }
    static String sourceLabel(String source){
        switch(source){case "L1":return "LB";case "R1":return "RB";case "L2":return "LT";case "R2":return "RT";case "L3":return "Left stick press";case "R3":return "Right stick press";default:return source.replaceAll("([a-z])([A-Z])","$1 $2");}
    }
    private final Sink sink;
    private List<Layer> layers=defaultLayers();
    private final Map<String,Float> held=new LinkedHashMap<>();
    // Latch control actions on press, so their release is independent of the new layer's bindings.
    private final Map<String,String> controls=new LinkedHashMap<>();
    private final Map<String,Integer> temporary=new LinkedHashMap<>(),counts=new HashMap<>();
    private int selected;
    private boolean active;
    float deadzone=.20f,sensitivity=700;
    ControllerInput(Sink sink){this.sink=sink;}
    void configure(List<Layer> next,float deadzone,float sensitivity){
        if(!Float.isFinite(deadzone)||deadzone<.05f||deadzone>.8f)throw new IllegalArgumentException("Controller deadzone must be between 0.05 and 0.8");
        if(!Float.isFinite(sensitivity)||sensitivity<50||sensitivity>2500)throw new IllegalArgumentException("Pointer speed must be between 50 and 2500");
        if(next.isEmpty()||next.size()>MAX_LAYERS)throw new IllegalArgumentException("Choose between 1 and 6 layers");
        Set<String> names=new HashSet<>();
        for(int i=0;i<next.size();i++){
            Layer layer=next.get(i);
            if(layer.name.isEmpty()||layer.name.length()>24||layer.name.chars().anyMatch(Character::isISOControl)||!names.add(layer.name.toLowerCase(Locale.ROOT)))throw new IllegalArgumentException("Layer names must be unique and contain 1–24 printable characters");
            if(!layer.bindings.keySet().equals(new HashSet<>(SOURCES)))throw new IllegalArgumentException("Every layer must contain all controller sources");
            for(String value:layer.bindings.values()){
                if(!(i>0&&value.equals("Inherit"))&&!ACTIONS.contains(value))throw new IllegalArgumentException("Unknown controller action: "+value);
                if(layerTarget(value)>=next.size())throw new IllegalArgumentException("Binding targets a layer that does not exist");
            }
        }
        releaseAll();layers=new ArrayList<>(next);selected=0;this.deadzone=deadzone;this.sensitivity=sensitivity;sink.layer(currentLayer(),layerName());
    }
    int currentLayer(){int result=selected;for(int target:temporary.values())result=target;return result;}
    String layerName(){return layers.get(currentLayer()).name;}
    int layerCount(){return layers.size();}
    void activate(boolean enabled){if(!enabled)releaseAll();active=enabled;}
    boolean active(){return active;}
    private String action(String source){String value=layers.get(currentLayer()).bindings.get(source);return value.equals("Inherit")?layers.get(0).bindings.get(source):value;}
    private static boolean isModifier(String action){return action.equals("ShiftLeft")||action.equals("ControlLeft")||action.equals("AltLeft");}
    private void releaseOutputs(){
        List<String> old=new ArrayList<>(counts.keySet());old.sort(Comparator.comparing(ControllerInput::isModifier));
        counts.clear();for(String a:old)sink.button(a,false);
    }
    private void reconcile(){
        Map<String,Integer> next=new LinkedHashMap<>();
        for(String source:held.keySet()){
            if(controls.containsKey(source))continue;
            String action=action(source);
            if(action.equals("None")||action.startsWith("Pointer")||action.startsWith("Wheel")||APP_ACTIONS.contains(action)||isLayerAction(action))continue;
            for(String atom:action.split("\\+"))next.put(atom,next.getOrDefault(atom,0)+1);
        }
        List<String> old=new ArrayList<>(counts.keySet());old.sort(Comparator.comparing(ControllerInput::isModifier));
        for(String a:old)if(!next.containsKey(a))sink.button(a,false);
        List<String> fresh=new ArrayList<>(next.keySet());fresh.sort(Comparator.comparing(ControllerInput::isModifier).reversed());
        for(String a:fresh)if(!counts.containsKey(a))sink.button(a,true);
        counts.clear();counts.putAll(next);
    }
    private void changedLayer(int before){
        if(before!=currentLayer()){releaseOutputs();reconcile();sink.layer(currentLayer(),layerName());}
        else reconcile();
    }
    void value(String source,float magnitude){
        if(!SOURCES.contains(source)||!Float.isFinite(magnitude))return;
        if(!active)return;
        magnitude=Math.max(0,Math.min(1,magnitude));boolean before=held.containsKey(source);
        String command=controls.getOrDefault(source,action(source));
        boolean down=command.startsWith("Pointer")?magnitude>0:magnitude>(before?.20f:.45f);
        if(down)held.put(source,magnitude);else held.remove(source);
        if(down==before)return;
        int previous=currentLayer();
        if(!down){controls.remove(source);temporary.remove(source);changedLayer(previous);return;}
        if(isLayerAction(command)){
            controls.put(source,command);
            if(command.equals("LayerNext"))selected=(selected+1)%layers.size();
            else if(command.equals("LayerPrevious"))selected=(selected+layers.size()-1)%layers.size();
            else if(command.startsWith("HoldLayer"))temporary.put(source,layerTarget(command));
            else selected=layerTarget(command);
            changedLayer(previous);return;
        }
        reconcile();
        if(command.startsWith("Wheel"))sink.wheel(command.equals("WheelUp")?1:-1);
        if(APP_ACTIONS.contains(command))sink.button(command,true);
    }
    void physicalValue(String source,float magnitude){value(source,magnitude);}
    void axis(String negative,String positive,float value){float amount=Math.abs(value)<=deadzone?0:(Math.abs(value)-deadzone)/(1-deadzone);value(negative,value<0?amount:0);value(positive,value>0?amount:0);}
    void tick(float seconds){
        if(!active)return;float dx=0,dy=0;
        for(Map.Entry<String,Float> e:held.entrySet())switch(controls.containsKey(e.getKey())?"None":action(e.getKey())){
            case "PointerLeft":dx-=e.getValue();break;case "PointerRight":dx+=e.getValue();break;case "PointerUp":dy-=e.getValue();break;case "PointerDown":dy+=e.getValue();break;
            default:break;
        }
        if(dx!=0||dy!=0)sink.pointer(dx*sensitivity*Math.min(seconds,.05f),dy*sensitivity*Math.min(seconds,.05f));
    }
    void releaseAll(){int before=currentLayer();releaseOutputs();held.clear();controls.clear();temporary.clear();if(before!=currentLayer())sink.layer(currentLayer(),layerName());}
}
