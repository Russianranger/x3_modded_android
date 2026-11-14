package io.github.russianranger.x3;

import android.content.Context;
import android.graphics.*;
import android.view.View;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.*;

/**
 * Non-interactive controller help card drawn above the game (never injected into it).
 * Labels come from assets/controls/overlay-data.json (generated with the default profile);
 * when the live binding differs from the default, the raw binding is shown and marked custom.
 * Layout uses the same 1280x720 coordinates as overlay/*.svg, scaled to the view.
 */
final class HelpOverlayView extends View {
    private static final float W=1280,H=720;
    private static final int[] FACE={0xff3fb950,0xfff85149,0xff58a6ff,0xffd29922};
    private final Paint fill=new Paint(Paint.ANTI_ALIAS_FLAG),stroke=new Paint(Paint.ANTI_ALIAS_FLAG),text=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path body=new Path();
    private JSONArray defaults=new JSONArray();
    private JSONObject state;
    private int layer;

    HelpOverlayView(Context context) {
        super(context);setClickable(false);setFocusable(false);
        stroke.setStyle(Paint.Style.STROKE);
        body.moveTo(520,300);body.lineTo(760,300);body.quadTo(820,300,835,360);body.lineTo(860,470);body.quadTo(868,525,825,530);
        body.quadTo(795,532,775,500);body.lineTo(745,455);body.lineTo(535,455);body.lineTo(505,500);body.quadTo(485,532,455,530);
        body.quadTo(412,525,420,470);body.lineTo(445,360);body.quadTo(460,300,520,300);body.close();
        try(InputStream in=context.getAssets().open("controls/overlay-data.json")){
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[16384];int n;while((n=in.read(b))>0)out.write(b,0,n);
            defaults=new JSONObject(out.toString("UTF-8")).getJSONArray("layers");
        }catch(Exception e){defaults=new JSONArray();}
    }

    /** state = ControllerManager.state(); layer = index of the active layer. */
    void show(JSONObject controllerState,int activeLayer){state=controllerState;layer=activeLayer;invalidate();}

    private static final class Row {String tag,label,key;boolean inherited,verify,custom;}

    private Row row(String source,String tag) {
        Row r=new Row();r.tag=tag;
        JSONArray layers=state==null?null:state.optJSONArray("layers");
        String action="None";boolean inherited=false;
        if(layers!=null&&layer<layers.length()){
            JSONObject bindings=layers.optJSONObject(layer).optJSONObject("bindings");
            action=bindings==null?"None":bindings.optString(source,"None");
            if(action.equals("Inherit")){inherited=true;JSONObject first=layers.optJSONObject(0).optJSONObject("bindings");action=first==null?"None":first.optString(source,"None");}
        }
        r.inherited=inherited&&layer>0;
        JSONObject known=defaultControl(source);
        if(known!=null&&action.equals(known.optString("x3_action"))){
            r.label=known.optString("short");r.key=known.optString("key_display");r.verify="verify".equals(known.optString("status"));
        } else {
            r.custom=!action.equals("None");r.label=r.custom?pretty(action)+" (custom)":"—";r.key="";
        }
        return r;
    }

    private JSONObject defaultControl(String source) {
        if(layer>=defaults.length()||state==null)return null;
        JSONObject meta=defaults.optJSONObject(layer);JSONArray layers=state.optJSONArray("layers");
        JSONObject live=layers==null?null:layers.optJSONObject(layer);
        if(meta==null||live==null||!meta.optString("name").equals(live.optString("name")))return null;
        JSONArray controls=meta.optJSONArray("controls");
        for(int i=0;controls!=null&&i<controls.length();i++)if(source.equals(controls.optJSONObject(i).optString("source")))return controls.optJSONObject(i);
        return null;
    }

    private static String pretty(String action) {
        int target=ControllerInput.layerTarget(action);
        if(target>=0)return (action.startsWith("Hold")?"Hold layer ":"Layer ")+(target+1);
        return action.replace("ShiftLeft+","Shift+").replace("ControlLeft+","Ctrl+").replace("AltLeft+","Alt+")
            .replace("Key","").replace("Digit","").replace("Numpad","Num ").replace("Arrow","");
    }

    private int accent() {
        JSONObject meta=layer<defaults.length()?defaults.optJSONObject(layer):null;
        try{return Color.parseColor(meta==null?"#4cc2ff":meta.optString("accent","#4cc2ff"));}catch(IllegalArgumentException e){return 0xff4cc2ff;}
    }

    @Override protected void onDraw(Canvas canvas) {
        if(state==null)return;
        float scale=Math.min(getWidth()/W,getHeight()/H);
        canvas.drawColor(0xe6070b10);
        canvas.save();canvas.translate((getWidth()-W*scale)/2,(getHeight()-H*scale)/2);canvas.scale(scale,scale);
        int accent=accent();
        JSONArray layers=state.optJSONArray("layers");int count=layers==null?0:layers.length();
        String name=layers!=null&&layer<count?layers.optJSONObject(layer).optString("name"):"";
        JSONObject meta=layer<defaults.length()?defaults.optJSONObject(layer):null;
        boolean hold=meta!=null&&"hold".equals(meta.optString("kind"));
        text.setTypeface(Typeface.DEFAULT);text.setTextSize(12);text.setColor(accent);text.setLetterSpacing(.15f);
        canvas.drawText("LAYER "+(layer+1)+" / "+count+" · "+(hold?"HOLD":"BASE"),40,44,text);
        text.setLetterSpacing(0);text.setTypeface(Typeface.DEFAULT_BOLD);text.setTextSize(32);text.setColor(0xffe6edf3);
        canvas.drawText(name,40,80,text);
        float nameWidth=text.measureText(name);
        text.setTypeface(Typeface.DEFAULT);text.setTextSize(15);text.setColor(0xff8b98a8);
        if(meta!=null)canvas.drawText(meta.optString("blurb"),60+nameWidth,80,text);
        // Layer tabs, right-aligned.
        float x=W-40;text.setTextSize(13);
        for(int i=count-1;i>=0;i--){
            String label=layers.optJSONObject(i).optString("name");float w=text.measureText(label)+26;x-=w;
            int color=i<defaults.length()?parse(defaults.optJSONObject(i).optString("accent")):accent;
            fill.setColor(color);fill.setAlpha(i==layer?230:22);canvas.drawRoundRect(x,30,x+w,56,13,13,fill);
            stroke.setColor(color);stroke.setStrokeWidth(1);canvas.drawRoundRect(x,30,x+w,56,13,13,stroke);
            text.setColor(i==layer?0xff0b1118:0xffc9d4df);text.setTextAlign(Paint.Align.CENTER);canvas.drawText(label,x+w/2,48,text);text.setTextAlign(Paint.Align.LEFT);
            x-=8;
        }
        drawController(canvas,accent);
        float y=100;
        y=box(canvas,40,y,"TRIGGER",new Row[]{row("L2","LT")},505,286,true,accent);
        y=box(canvas,40,y,"BUMPER",new Row[]{row("L1","LB")},528,306,true,accent);
        y=box(canvas,40,y,"",new Row[]{row("Select","Select")},612,352,true,accent);
        y=box(canvas,40,y,"LEFT STICK",stick("Left","L3"),540,362,true,accent);
        box(canvas,40,y,"D-PAD",new Row[]{row("DpadUp","↑"),row("DpadRight","→"),row("DpadDown","↓"),row("DpadLeft","←")},590,428,true,accent);
        y=100;
        y=box(canvas,860,y,"TRIGGER",new Row[]{row("R2","RT")},775,286,false,accent);
        y=box(canvas,860,y,"BUMPER",new Row[]{row("R1","RB")},752,306,false,accent);
        y=box(canvas,860,y,"",new Row[]{row("Start","Start")},668,352,false,accent);
        y=box(canvas,860,y,"FACE BUTTONS",new Row[]{row("Y","Y"),row("X","X"),row("B","B"),row("A","A")},745,360,false,accent);
        box(canvas,860,y,"RIGHT STICK",stick("Right","R3"),690,428,false,accent);
        text.setTextAlign(Paint.Align.CENTER);text.setTextSize(13);text.setColor(0xffc9d4df);
        canvas.drawText("Hold Select = this overlay + System layer · Select + D-pad switches layers · Select + Start pins it · Hold LT = Combat",640,660,text);
        text.setTextSize(12);text.setColor(0xff7d8a99);
        canvas.drawText("Dimmed = inherited from layer 1 · amber dot = key not yet confirmed in AP 3.3 · (custom) = your own mapping",640,684,text);
        text.setTextAlign(Paint.Align.LEFT);
        canvas.restore();
    }

    private Row[] stick(String side,String press) {
        Row up=row(side+"Up","↑"),right=row(side+"Right","→"),down=row(side+"Down","↓"),left=row(side+"Left","←");
        Row click=row(press,"press");
        if(up.key.equals("Mouse")&&right.key.equals("Mouse")&&down.key.equals("Mouse")&&left.key.equals("Mouse")){
            up.tag="move";up.label="Mouse pointer";return new Row[]{up,click};
        }
        return new Row[]{up,right,down,left,click};
    }

    private static int parse(String color){try{return Color.parseColor(color);}catch(IllegalArgumentException e){return 0xff4cc2ff;}}

    private float box(Canvas canvas,float x,float y,String title,Row[] rows,float ax,float ay,boolean left,int accent) {
        float width=380,h=26+26*rows.length+(title.isEmpty()?-16:6);
        fill.setColor(0xeb111a25);canvas.drawRoundRect(x,y,x+width,y+h,10,10,fill);
        stroke.setColor(0xff243244);stroke.setStrokeWidth(1);canvas.drawRoundRect(x,y,x+width,y+h,10,10,stroke);
        float ry=y+22;
        if(!title.isEmpty()){text.setTextSize(11);text.setColor(0xff8b98a8);text.setLetterSpacing(.12f);canvas.drawText(title,x+12,y+18,text);text.setLetterSpacing(0);ry=y+46;}
        for(Row r:rows){drawRow(canvas,x,ry,width,r,accent);ry+=26;}
        float ex=left?x+width:x,ey=y+Math.min(h/2,24),elbow=ex+(left?26:-26);
        stroke.setColor(0xff3b4c61);stroke.setStrokeWidth(1.4f);
        canvas.drawLine(ex,ey,elbow,ey,stroke);canvas.drawLine(elbow,ey,ax,ay,stroke);
        fill.setColor(accent);canvas.drawCircle(ax,ay,3,fill);
        return y+h+10;
    }

    private void drawRow(Canvas canvas,float x,float y,float width,Row r,int accent) {
        int alpha=r.inherited?107:255;
        if(!r.inherited){fill.setColor(r.custom?0xffe3b341:accent);canvas.drawRoundRect(x,y-14,x+3,y+6,1.5f,1.5f,fill);}
        int face="ABXY".indexOf(r.tag.length()==1?r.tag.charAt(0):'?');
        if(face>=0&&r.tag.length()==1){
            fill.setColor(FACE[face]);fill.setAlpha(alpha);canvas.drawCircle(x+20,y-4,10,fill);
            text.setTypeface(Typeface.DEFAULT_BOLD);text.setTextSize(12);text.setColor(0xff0b1118);text.setAlpha(alpha);text.setTextAlign(Paint.Align.CENTER);
            canvas.drawText(r.tag,x+20,y+0.5f,text);text.setTextAlign(Paint.Align.LEFT);text.setTypeface(Typeface.DEFAULT);
        } else {text.setTextSize(12);text.setColor(0xff8b98a8);text.setAlpha(alpha);canvas.drawText(r.tag,x+10,y,text);}
        text.setTextSize(15);text.setColor(0xffe6edf3);text.setAlpha(alpha);canvas.drawText(r.label,x+58,y,text);
        if(!r.key.isEmpty()){
            text.setTypeface(Typeface.MONOSPACE);text.setTextSize(12);
            float w=text.measureText(r.key)+14,right=x+width-12;
            fill.setColor(0xff0d141d);fill.setAlpha(alpha);canvas.drawRoundRect(right-w,y-14,right,y+6,5,5,fill);
            stroke.setColor(accent);stroke.setAlpha(r.inherited?60:140);stroke.setStrokeWidth(1);canvas.drawRoundRect(right-w,y-14,right,y+6,5,5,stroke);
            text.setColor(0xffe6edf3);text.setAlpha(alpha);text.setTextAlign(Paint.Align.CENTER);canvas.drawText(r.key,right-w/2,y,text);
            text.setTextAlign(Paint.Align.LEFT);text.setTypeface(Typeface.DEFAULT);
        }
        if(r.verify){fill.setColor(0xffe3b341);fill.setAlpha(alpha);canvas.drawCircle(x+width-4,y-12,3.5f,fill);}
        text.setAlpha(255);fill.setAlpha(255);stroke.setAlpha(255);
    }

    private void drawController(Canvas canvas,int accent) {
        fill.setColor(0xff161f2b);canvas.drawPath(body,fill);
        stroke.setColor(0xff2c3a4d);stroke.setStrokeWidth(2);canvas.drawPath(body,stroke);
        stroke.setColor(accent);stroke.setStrokeWidth(2);fill.setColor(0xff0f1620);
        canvas.drawRoundRect(485,276,529,290,6,6,stroke);canvas.drawRoundRect(751,276,795,290,6,6,stroke);
        canvas.drawRoundRect(500,296,560,304,4,4,stroke);canvas.drawRoundRect(720,296,780,304,4,4,stroke);
        canvas.drawCircle(540,362,24,fill);canvas.drawCircle(540,362,24,stroke);
        canvas.drawCircle(690,428,24,fill);canvas.drawCircle(690,428,24,stroke);
        Path dpad=new Path();dpad.moveTo(582,408);dpad.rLineTo(16,0);dpad.rLineTo(0,12);dpad.rLineTo(12,0);dpad.rLineTo(0,16);dpad.rLineTo(-12,0);
        dpad.rLineTo(0,12);dpad.rLineTo(-16,0);dpad.rLineTo(0,-12);dpad.rLineTo(-12,0);dpad.rLineTo(0,-16);dpad.rLineTo(12,0);dpad.close();
        canvas.drawPath(dpad,fill);canvas.drawPath(dpad,stroke);
        canvas.drawRoundRect(602,346,622,358,6,6,stroke);canvas.drawRoundRect(658,346,678,358,6,6,stroke);
        float[][] faces={{745,384},{769,360},{721,360},{745,336}};String tags="ABXY";
        for(int i=0;i<4;i++){
            fill.setColor(FACE[i]);canvas.drawCircle(faces[i][0],faces[i][1],11,fill);
            text.setTypeface(Typeface.DEFAULT_BOLD);text.setTextSize(11);text.setColor(0xff0b1118);text.setTextAlign(Paint.Align.CENTER);
            canvas.drawText(String.valueOf(tags.charAt(i)),faces[i][0],faces[i][1]+4,text);
        }
        text.setTextAlign(Paint.Align.LEFT);text.setTypeface(Typeface.DEFAULT);
    }
}
