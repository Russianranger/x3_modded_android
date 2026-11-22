// Adapted from trasc-server-android ClientActivity.java (commit 99e8c86f).
// X3 changes: no EverQuest commands / mouse-look tile, help overlay (peek while System is held, pin
// on demand), app actions TextInput and HelpOverlayToggle from the controller. Native Surface is an
// option (0.1.12): TRASC's first Thor measurement had it slower, its batched transport later
// delivered 59.7 frames/s against RFB's 40.7; the RFB connection then carries input only, and a
// failed surface falls back to RFB frames.
package io.github.russianranger.x3;

import android.app.*;
import android.content.res.ColorStateList;
import android.graphics.*;
import android.graphics.drawable.*;
import android.net.*;
import android.os.*;
import android.view.*;
import android.widget.*;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.util.concurrent.*;

/** The embedded Wine display. Back returns to the launcher without stopping the game. */
public final class GameActivity extends Activity {
    private GameRuntime runtime;
    private ControllerManager controller;
    private GameView display;
    private io.github.russianranger.trasc.NativePresentation nativeDisplay;
    private volatile boolean nativeActive;
    private String displayRate="";
    private HelpOverlayView overlay;
    private TextView status,layerBanner;
    private final Runnable hideLayer=()->{if(layerBanner!=null)layerBanner.animate().alpha(0f).setDuration(250).start();};
    private FrameLayout menuLayer;
    private LinearLayout menu;
    private ImageButton gear;
    private boolean menuOpen,keyboardOpen,mappingsOpen,overlayPinned,overlayPeek,failureShown;
    private int activeLayer;
    private JSONArray overlayLayers=new JSONArray();
    private String displayError;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final Runnable refresh=new Runnable(){@Override public void run(){
        JSONObject launch=runtime.launchState();
        String phase=launch==null?runtime.status:launch.optString("phase").replace('_',' ');
        if(!runtime.alive())phase="Game stopped · return to the launcher to start again";
        if(launch!=null&&launch.has("error"))phase=launch.optString("error");
        if(displayError!=null&&(launch==null||!launch.has("error")))phase=displayError;
        StringBuilder text=new StringBuilder(phase);
        if(launch!=null){
            if(launch.has("renderer"))text.append("\n").append(launch.optString("renderer"));
            if(launch.has("dxvk_loaded"))text.append(" · DXVK ").append(launch.optString("dxvk_loaded"));
            text.append(nativeActive?" · native surface":" · RFB");
            if(launch.has("presentation_fallback"))text.append(" (native surface unavailable: ").append(launch.optString("presentation_fallback")).append(")");
            if(nativeActive&&nativeDisplay!=null)try{
                JSONObject surface=nativeDisplay.sample(System.nanoTime());
                if(surface.has("surface_posts_per_second"))displayRate=String.format(java.util.Locale.ROOT," %.0f/s",surface.optDouble("surface_posts_per_second"));
                text.append(displayRate);
            }catch(org.json.JSONException ignored){}
            JSONObject present=launch.optJSONObject("wine_present");
            if(present!=null)text.append(String.format(java.util.Locale.ROOT," · Wine %.1f fps",present.optDouble("per_second")));
            org.json.JSONArray pauses=launch.optJSONArray("present_pauses_seconds");
            if(pauses!=null&&pauses.length()>0)   // a pause in presenting = a loading screen
                text.append(String.format(java.util.Locale.ROOT," · last load %.0f s",pauses.optDouble(pauses.length()-1)));
            if(launch.has("warning"))text.append("\n").append(launch.optString("warning"));
        }
        text.append("\nLayer ").append(controller.layerLabel());
        status.setText(text);
        if(launch!=null&&launch.has("error")&&!failureShown&&hasWindowFocus()&&!isFinishing()) {
            failureShown=true;controller.capture(false);display.input.releaseAll();setMenuOpen(true);
            new AlertDialog.Builder(GameActivity.this).setTitle("Game stopped with an error").setMessage(launch.optString("error"))
                .setPositiveButton("Return to launcher",(dialog,which)->finish()).setCancelable(false).show();
        }
        handler.postDelayed(this,1000);
    }};

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);setVolumeControlStream(android.media.AudioManager.STREAM_MUSIC);runtime=GameRuntime.get(this);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        FrameLayout layout=new FrameLayout(this);layout.setBackgroundColor(Color.BLACK);
        display=new GameView();layout.addView(display,new FrameLayout.LayoutParams(-1,-1));
        JSONObject launched=runtime.launchState();
        nativeActive=launched!=null&&"native_surface".equals(launched.optString("presentation_active"));
        if(nativeActive){
            nativeDisplay=new io.github.russianranger.trasc.NativePresentation(this,runtime.frameSocket(),new io.github.russianranger.trasc.NativePresentation.Events(){
                public void failed(String reason){nativeFailed(reason);}
                public void size(int width,int height){display.nativeSize(width,height);}
            });
            // Under the (then transparent) input view: Surface pixels show through it.
            layout.addView(nativeDisplay,0,new FrameLayout.LayoutParams(-1,-1,Gravity.CENTER));
        }
        overlay=new HelpOverlayView(this);overlay.setVisibility(View.GONE);layout.addView(overlay,new FrameLayout.LayoutParams(-1,-1));
        try(InputStream in=getAssets().open("controls/overlay-data.json")){
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[16384];int n;while((n=in.read(b))>0)out.write(b,0,n);
            overlayLayers=new JSONObject(out.toString("UTF-8")).getJSONArray("layers");
        }catch(Exception ignored){}
        menuLayer=new FrameLayout(this);menuLayer.setVisibility(View.GONE);menuLayer.setOnClickListener(v->setMenuOpen(false));
        layout.addView(menuLayer,new FrameLayout.LayoutParams(-1,-1));
        ScrollView scroll=new ScrollView(this);
        menu=new LinearLayout(this);menu.setOrientation(LinearLayout.VERTICAL);menu.setPadding(dp(12),dp(8),dp(12),dp(12));
        menu.setBackground(panel(0xd010191c));menu.setOnClickListener(v->{});
        addMenuButton("Return to launcher",v->finish());
        addMenuButton("Keyboard (type text)",v->textDialog());
        addMenuButton("Controller mappings",v->controllerDialog());
        addMenuButton("Show / hide controller help",v->{setMenuOpen(false);toggleOverlayPin();});
        addMenuButton("Esc",v->{setMenuOpen(false);display.input.key("menu-esc",0xff1b,true);display.input.key("menu-esc",0xff1b,false);});
        addMenuButton("Capture external mouse",v->{setMenuOpen(false);display.post(()->display.requestPointerCapture());});
        addMenuButton("Stop game",v->new AlertDialog.Builder(this).setTitle("Stop the game?").setMessage("Unsaved progress is lost.")
            .setPositiveButton("Stop",(d,w)->new Thread(()->{try{runtime.stop();}catch(Exception e){Logs.failure(runtime.paths.logs,"game_stop",e);}handler.post(this::finish);}).start())
            .setNegativeButton("Cancel",null).show());
        status=new TextView(this);status.setTextColor(0xffe2eded);status.setTextSize(12);status.setPadding(dp(4),dp(10),dp(4),0);
        menu.addView(status);scroll.addView(menu);
        FrameLayout.LayoutParams panelPosition=new FrameLayout.LayoutParams(dp(300),-2,Gravity.TOP|Gravity.RIGHT);
        panelPosition.setMargins(dp(12),dp(68),dp(12),dp(12));menuLayer.addView(scroll,panelPosition);
        gear=new ImageButton(this);gear.setImageResource(R.drawable.ic_gear);gear.setPadding(dp(12),dp(12),dp(12),dp(12));
        gear.setContentDescription("Open game menu");gear.setBackground(new RippleDrawable(ColorStateList.valueOf(0x55ffffff),panel(0x6010191c),null));
        gear.setAlpha(.6f);gear.setOnClickListener(v->setMenuOpen(!menuOpen));
        FrameLayout.LayoutParams gearPosition=new FrameLayout.LayoutParams(dp(48),dp(48),Gravity.TOP|Gravity.RIGHT);
        gearPosition.setMargins(0,dp(12),dp(12),0);layout.addView(gear,gearPosition);
        layerBanner=new TextView(this);layerBanner.setTextColor(0xb3ffffff);layerBanner.setTextSize(16);layerBanner.setGravity(Gravity.CENTER);
        layerBanner.setPadding(dp(12),dp(6),dp(12),dp(6));layerBanner.setBackground(panel(0x28081010));layerBanner.setAlpha(0f);
        layerBanner.setClickable(false);layerBanner.setFocusable(false);
        FrameLayout.LayoutParams bannerPosition=new FrameLayout.LayoutParams(-2,-2,Gravity.TOP|Gravity.CENTER_HORIZONTAL);bannerPosition.topMargin=dp(12);
        layout.addView(layerBanner,bannerPosition);
        setContentView(layout);immersive();
        controller=new ControllerManager(this,runtime.paths.controllerProfile(),event->{
            switch(event.optString("type")) {
                case "button": {
                    String action=event.optString("action");
                    if(action.equals("ClientMenu")){setMenuOpen(true);break;}
                    if(action.equals("HelpOverlayToggle")){toggleOverlayPin();break;}
                    if(action.equals("TextInput")){textDialog();break;}
                    if(display!=null)display.input.action(action,event.optBoolean("down"));break;
                }
                case "pointer":if(display!=null)display.input.move((float)event.optDouble("x"),(float)event.optDouble("y"));break;
                case "wheel":if(display!=null)display.input.wheel(event.optInt("y"));break;
                case "layer":layerChanged(event.optInt("x"),event.optString("action"));break;
                default:break;
            }
        });
        setMenuOpen(false);display.connect();handler.post(refresh);
    }

    private void layerChanged(int index,String name){
        activeLayer=index;
        JSONObject meta=index<overlayLayers.length()?overlayLayers.optJSONObject(index):null;
        overlayPeek=meta!=null&&"peek".equals(meta.optString("overlay"))&&name.equals(meta.optString("name"));
        updateOverlay();
        if(layerBanner==null)return;
        handler.removeCallbacks(hideLayer);layerBanner.animate().cancel();layerBanner.setText("Layer "+(index+1)+" · "+name);layerBanner.setAlpha(1f);
        handler.postDelayed(hideLayer,1500);
    }
    private void toggleOverlayPin(){overlayPinned=!overlayPinned;updateOverlay();}
    private void updateOverlay(){
        if(overlay==null||controller==null)return;
        boolean visible=(overlayPinned||overlayPeek)&&!menuOpen&&!keyboardOpen&&!mappingsOpen;
        if(visible)try{overlay.show(controller.state(),activeLayer);}catch(org.json.JSONException ignored){}
        overlay.setVisibility(visible?View.VISIBLE:View.GONE);
    }

    private int dp(int value){return Math.round(value*getResources().getDisplayMetrics().density);}
    private GradientDrawable panel(int color){GradientDrawable background=new GradientDrawable();background.setColor(color);background.setCornerRadius(dp(16));return background;}
    private Button addMenuButton(String title,View.OnClickListener action){Button button=new Button(this);button.setText(title);button.setAllCaps(false);button.setTextColor(Color.WHITE);button.setMinHeight(dp(48));button.setBackground(new RippleDrawable(ColorStateList.valueOf(0x44ffffff),panel(0x18ffffff),null));button.setOnClickListener(action);LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(-1,dp(48));params.topMargin=dp(4);menu.addView(button,params);return button;}
    private void immersive(){
        if(Build.VERSION.SDK_INT>=30){
            getWindow().setDecorFitsSystemWindows(false);
            WindowInsetsController insets=getWindow().getInsetsController();
            if(insets!=null){insets.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);insets.hide(WindowInsets.Type.systemBars());}
        }else getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY|View.SYSTEM_UI_FLAG_FULLSCREEN|View.SYSTEM_UI_FLAG_HIDE_NAVIGATION|View.SYSTEM_UI_FLAG_LAYOUT_STABLE|View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN|View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
    }
    private boolean gameInputActive(){return hasWindowFocus()&&!menuOpen&&!keyboardOpen&&!mappingsOpen&&!failureShown;}
    private void setMenuOpen(boolean open){
        menuOpen=open;menuLayer.setVisibility(open?View.VISIBLE:View.GONE);gear.setAlpha(open?1f:.6f);
        if(controller!=null)controller.capture(gameInputActive());
        if(open){display.input.releaseAll();display.releasePointerCapture();menu.getChildAt(0).requestFocus();}else display.requestFocus();
        updateOverlay();
    }
    private void controllerDialog(){
        mappingsOpen=true;controller.capture(false);display.input.releaseAll();updateOverlay();
        new ControllerDialog(this,controller,()->{mappingsOpen=false;controller.capture(gameInputActive());updateOverlay();}).show();
    }
    private void textDialog() {
        keyboardOpen=true;setMenuOpen(false);controller.capture(false);display.input.releaseAll();updateOverlay();
        EditText text=new EditText(this);text.setSingleLine(true);text.setHint("Text for the focused game field (ship names, save names…)");
        text.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(4096)});
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle("Keyboard").setView(text)
            .setPositiveButton("Type",(d,w)->display.input.text(text.getText().toString(),false))
            .setNeutralButton("Type + Enter",(d,w)->display.input.text(text.getText().toString(),true))
            .setNegativeButton("Cancel",null).create();
        dialog.setOnDismissListener(d->{keyboardOpen=false;display.requestFocus();immersive();controller.capture(gameInputActive());updateOverlay();});dialog.show();
        text.requestFocus();if(dialog.getWindow()!=null)dialog.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE);
    }
    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        if(gameInputActive()&&controller!=null&&controller.key(event))return true;
        if(display!=null&&gameInputActive()&&event.getKeyCode()!=KeyEvent.KEYCODE_BACK&&(event.getSource()&InputDevice.SOURCE_KEYBOARD)==InputDevice.SOURCE_KEYBOARD) {
            int symbol=physicalSymbol(event);
            if(symbol!=0&&(event.getAction()==KeyEvent.ACTION_DOWN||event.getAction()==KeyEvent.ACTION_UP)){display.input.key("physical:"+event.getKeyCode(),symbol,event.getAction()==KeyEvent.ACTION_DOWN);return true;}
        }
        return super.dispatchKeyEvent(event);
    }
    static int physicalSymbol(KeyEvent event) {
        switch(event.getKeyCode()) {
            case KeyEvent.KEYCODE_ENTER:return 0xff0d;case KeyEvent.KEYCODE_NUMPAD_ENTER:return 0xff8d;case KeyEvent.KEYCODE_ESCAPE:return 0xff1b;case KeyEvent.KEYCODE_TAB:return 0xff09;case KeyEvent.KEYCODE_DEL:return 0xff08;
            case KeyEvent.KEYCODE_DPAD_LEFT:return 0xff51;case KeyEvent.KEYCODE_DPAD_UP:return 0xff52;case KeyEvent.KEYCODE_DPAD_RIGHT:return 0xff53;case KeyEvent.KEYCODE_DPAD_DOWN:return 0xff54;
            case KeyEvent.KEYCODE_SHIFT_LEFT:return 0xffe1;case KeyEvent.KEYCODE_SHIFT_RIGHT:return 0xffe2;case KeyEvent.KEYCODE_CTRL_LEFT:return 0xffe3;case KeyEvent.KEYCODE_CTRL_RIGHT:return 0xffe4;
            case KeyEvent.KEYCODE_ALT_LEFT:return 0xffe9;case KeyEvent.KEYCODE_ALT_RIGHT:return 0xffea;case KeyEvent.KEYCODE_BREAK:return 0xff13;
            case KeyEvent.KEYCODE_MOVE_HOME:return 0xff50;case KeyEvent.KEYCODE_MOVE_END:return 0xff57;case KeyEvent.KEYCODE_PAGE_UP:return 0xff55;case KeyEvent.KEYCODE_PAGE_DOWN:return 0xff56;case KeyEvent.KEYCODE_INSERT:return 0xff63;case KeyEvent.KEYCODE_FORWARD_DEL:return 0xffff;
            case KeyEvent.KEYCODE_NUMPAD_ADD:return 0xffab;case KeyEvent.KEYCODE_NUMPAD_SUBTRACT:return 0xffad;
            default:break;
        }
        if(event.getKeyCode()>=KeyEvent.KEYCODE_NUMPAD_0&&event.getKeyCode()<=KeyEvent.KEYCODE_NUMPAD_9)return 0xffb0+event.getKeyCode()-KeyEvent.KEYCODE_NUMPAD_0;
        if(event.getKeyCode()>=KeyEvent.KEYCODE_F1&&event.getKeyCode()<=KeyEvent.KEYCODE_F12)return 0xffbe+event.getKeyCode()-KeyEvent.KEYCODE_F1;
        int code=event.getUnicodeChar(event.getMetaState()&(KeyEvent.META_SHIFT_ON|KeyEvent.META_CAPS_LOCK_ON));
        return code<=255?code:code<=0x10ffff?0x01000000|code:0;
    }
    @Override public boolean dispatchGenericMotionEvent(MotionEvent event){return gameInputActive()&&controller!=null&&controller.motion(event)||super.dispatchGenericMotionEvent(event);}
    @Override public void onBackPressed(){if(display.hasPointerCapture()){display.releasePointerCapture();setMenuOpen(true);return;}if(menuOpen)setMenuOpen(false);else super.onBackPressed();}
    @Override public void onWindowFocusChanged(boolean focus){super.onWindowFocusChanged(focus);if(focus&&!keyboardOpen)immersive();if(controller!=null)controller.capture(gameInputActive());if(!focus&&display!=null)display.input.releaseAll();}
    @Override protected void onPause(){if(controller!=null)controller.capture(false);if(display!=null)display.input.releaseAll();super.onPause();}
    /** The surface reader stopped: show RFB frames instead, in the same session. */
    private void nativeFailed(String reason){
        if(!nativeActive)return;
        nativeActive=false;Logs.failure(runtime.paths.logs,"native_surface",new IOException(reason==null?"failed":reason));
        if(nativeDisplay!=null){nativeDisplay.close();nativeDisplay.setVisibility(View.GONE);}
        display.send(r->r.request(false));display.postInvalidate();
    }
    @Override protected void onDestroy(){if(nativeDisplay!=null)nativeDisplay.close();handler.removeCallbacksAndMessages(null);if(layerBanner!=null)layerBanner.animate().cancel();if(controller!=null)controller.close();if(display!=null)display.close();super.onDestroy();}

    private final class GameView extends View implements RfbConnection.Screen {
        private final Object pixelsLock=new Object();
        private Bitmap bitmap;
        private int[] copyBuffer=new int[0];
        private int frameWidth=1280,frameHeight=720;
        private final Paint paint=new Paint(Paint.FILTER_BITMAP_FLAG);
        private final RectF bounds=new RectF();
        private final ExecutorService writer=Executors.newSingleThreadExecutor();
        private volatile LocalSocket socket,inputSocket;
        private volatile RfbConnection connection;
        private volatile RelativeInput relative;
        private volatile boolean closed;
        final DisplayInput input=new DisplayInput(new DisplayInput.Sink(){
            public void key(int sym,boolean down){send(r->r.key(sym,down));}
            public void pointer(int x,int y,int buttons){if(!sendRelative(0,x,y,buttons))send(r->r.pointer(x,y,buttons));}
            public boolean relative(int dx,int dy,int buttons){return sendRelative(1,dx,dy,buttons);}
            public boolean buttons(int buttons){return sendRelative(2,0,0,buttons);}
        });
        interface Send {void write(RfbConnection connection)throws IOException;}
        GameView(){super(GameActivity.this);setFocusable(true);setFocusableInTouchMode(true);}
        void send(Send send){if(!closed)writer.execute(()->{try{RfbConnection r=connection;if(r!=null)send.write(r);}catch(IOException e){failure(e);}});}
        boolean sendRelative(int type,int x,int y,int mask){
            if(closed||relative==null)return false;
            writer.execute(()->{try{RelativeInput target=relative;if(target!=null)target.send(type,x,y,mask);}catch(IOException e){closeInput();}});return true;
        }
        void closeInput(){relative=null;try{if(inputSocket!=null)inputSocket.close();}catch(IOException ignored){}inputSocket=null;}
        void connect(){new Thread(()->{
            try {
                LocalSocket local=new LocalSocket();socket=local;if(closed)return;
                File displayPath=runtime.displaySocket();TransientPaths.validateSocket(displayPath);
                local.connect(new LocalSocketAddress(displayPath.getPath(),LocalSocketAddress.Namespace.FILESYSTEM));
                local.setSoTimeout(15000);
                // Native surface: RFB carries keys and pointer only, no frames.
                RfbConnection r=new RfbConnection(local.getInputStream(),local.getOutputStream(),this);r.handshake(!nativeActive);
                local.setSoTimeout(0);connection=r;
                new Thread(this::connectInput,"x3-input-connect").start();
                while(!closed)r.readUpdate();
            }catch(IOException e){if(!closed)failure(e);}
            finally{closeInput();try{if(socket!=null)socket.close();}catch(IOException ignored){}connection=null;}
        },"x3-display").start();}
        /**
         * The relative-mouse helper opens input.sock a moment after the display socket appears (first
         * Thor run: one try, 0.3 s too early, left the right stick dead all session). Retry for 30 s.
         */
        void connectInput(){
            IOException last=null;
            for(int attempt=0;attempt<60&&!closed;attempt++){
                try{
                    LocalSocket control=new LocalSocket();inputSocket=control;
                    File inputPath=runtime.inputSocket();TransientPaths.validateSocket(inputPath);
                    control.connect(new LocalSocketAddress(inputPath.getPath(),LocalSocketAddress.Namespace.FILESYSTEM));control.setSoTimeout(3000);
                    RelativeInput channel=new RelativeInput(control.getInputStream(),control.getOutputStream());control.setSoTimeout(0);
                    if(closed){closeInput();return;}
                    relative=channel;return;
                }catch(IOException e){last=e;closeInput();}
                try{Thread.sleep(500);}catch(InterruptedException e){Thread.currentThread().interrupt();return;}
            }
            if(last!=null&&!closed)Logs.failure(runtime.paths.logs,"relative_input",last);
        }
        void failure(Exception error){if(closed)return;Logs.failure(runtime.paths.logs,"display",error);post(()->{displayError="Display disconnected: "+error.getMessage()+" · return to the launcher";if(!isDestroyed()){status.setText(displayError);setMenuOpen(true);}});}
        @Override public void resize(int w,int h){frameWidth=w;frameHeight=h;synchronized(pixelsLock){bitmap=Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888);}post(()->input.size(w,h));}
        @Override public void pixels(int x,int y,int w,int h,int[] colors){synchronized(pixelsLock){bitmap.setPixels(colors,0,w,x,y,w,h);}}
        @Override public void copy(int x,int y,int w,int h,int sx,int sy){synchronized(pixelsLock){if(copyBuffer.length<w*h)copyBuffer=new int[w*h];bitmap.getPixels(copyBuffer,0,w,sx,sy,w,h);bitmap.setPixels(copyBuffer,0,w,x,y,w,h);}}
        @Override public void updated(){postInvalidateOnAnimation();}
        /** Where the frame sits in this view: scaled to fit, centred. */
        private void fit(){
            if(frameWidth<1||frameHeight<1||getWidth()<1)return;
            float scale=Math.min((float)getWidth()/frameWidth,(float)getHeight()/frameHeight);float w=frameWidth*scale,h=frameHeight*scale;
            bounds.set((getWidth()-w)/2,(getHeight()-h)/2,(getWidth()+w)/2,(getHeight()+h)/2);
        }
        /** The native surface reported its frame size: same fit for the surface view and for input. */
        void nativeSize(int width,int height){
            frameWidth=width;frameHeight=height;input.size(width,height);fit();
            if(nativeDisplay!=null&&bounds.width()>0){
                FrameLayout.LayoutParams params=new FrameLayout.LayoutParams(Math.round(bounds.width()),Math.round(bounds.height()),Gravity.CENTER);
                nativeDisplay.setLayoutParams(params);
            }
        }
        @Override protected void onSizeChanged(int w,int h,int oldw,int oldh){super.onSizeChanged(w,h,oldw,oldh);if(nativeActive)post(()->nativeSize(frameWidth,frameHeight));}
        @Override protected void onDraw(Canvas canvas) {
            if(nativeActive){fit();return;}   // transparent: the surface below shows the game
            long started=System.nanoTime();canvas.drawColor(Color.BLACK);
            synchronized(pixelsLock){if(bitmap!=null){fit();canvas.drawBitmap(bitmap,null,bounds,paint);}}
            RfbConnection r=connection;if(r!=null)r.stats.drawn(System.nanoTime()-started);
        }
        private boolean position(MotionEvent event) {
            fit();
            if(bounds.width()==0||!bounds.contains(event.getX(),event.getY()))return false;
            input.position((event.getX()-bounds.left)*frameWidth/bounds.width(),(event.getY()-bounds.top)*frameHeight/bounds.height());return true;
        }
        @Override public boolean onTouchEvent(MotionEvent event) {
            if(!gameInputActive())return true;
            boolean mouse=event.isFromSource(InputDevice.SOURCE_MOUSE);
            if(event.getActionMasked()==MotionEvent.ACTION_CANCEL){input.releaseAll();return true;}
            if(event.getActionMasked()==MotionEvent.ACTION_UP){input.mouse("touch",1,false);if(mouse)mouseButtons(event);performClick();return true;}
            if(!position(event))return true;
            if(mouse)mouseButtons(event);else if(event.getActionMasked()==MotionEvent.ACTION_DOWN){requestFocus();input.mouse("touch",1,true);}
            return true;
        }
        private void mouseButtons(MotionEvent event){int mask=event.getButtonState();input.mouse("mouse-left",1,(mask&MotionEvent.BUTTON_PRIMARY)!=0);input.mouse("mouse-right",4,(mask&MotionEvent.BUTTON_SECONDARY)!=0);input.mouse("mouse-middle",2,(mask&MotionEvent.BUTTON_TERTIARY)!=0);}
        @Override public boolean onGenericMotionEvent(MotionEvent event) {
            if(!gameInputActive())return true;
            if(event.isFromSource(InputDevice.SOURCE_MOUSE)){position(event);mouseButtons(event);if(event.getAction()==MotionEvent.ACTION_SCROLL)input.wheel(Math.round(event.getAxisValue(MotionEvent.AXIS_VSCROLL)));return true;}
            return super.onGenericMotionEvent(event);
        }
        @Override public boolean onCapturedPointerEvent(MotionEvent event){
            if(!gameInputActive()){releasePointerCapture();return true;}
            input.move(event.getX()*frameWidth/Math.max(1,getWidth()),event.getY()*frameHeight/Math.max(1,getHeight()));
            mouseButtons(event);if(event.getActionMasked()==MotionEvent.ACTION_SCROLL)input.wheel(Math.round(event.getAxisValue(MotionEvent.AXIS_VSCROLL)));return true;
        }
        @Override public void onPointerCaptureChange(boolean captured){super.onPointerCaptureChange(captured);if(!captured)input.releaseAll();}
        @Override public boolean performClick(){super.performClick();return true;}
        private void closeSocket(){closeInput();try{if(socket!=null)socket.close();}catch(IOException ignored){}}
        void close(){input.releaseAll();closed=true;writer.execute(this::closeSocket);writer.shutdown();handler.postDelayed(this::closeSocket,250);}
    }
}
