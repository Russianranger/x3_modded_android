package io.github.russianranger.x3;

import android.app.*;
import android.content.*;
import android.content.res.ColorStateList;
import android.graphics.*;
import android.graphics.drawable.*;
import android.net.Uri;
import android.os.*;
import android.view.*;
import android.widget.*;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;
import java.util.concurrent.*;

/** Launcher: runtime install, game import/sync, launch options, controller mappings, logs. */
public final class MainActivity extends Activity {
    private static final int PICK_GAME=1,PICK_RUNTIME=2,EXPORT_LOGS=3;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private AppPaths paths;
    private GameRuntime runtime;
    private SharedPreferences prefs;
    private TextView statusView,runtimeView,gameView;
    private Spinner program,resolution,renderer,turnip,fps,presentation,cpu;
    private EditText arguments;
    private CheckBox audio,hud,diagnostics,soundDiagnostics,skipArchives,passthrough;
    private Button mediaButton;private JSONObject mediaManifest;
    private Button cancel;
    private volatile boolean operationRunning,cancelRequested;
    private volatile String operationStatus="";
    private ControllerManager controller;
    private final Runnable tick=new Runnable(){@Override public void run(){refresh();handler.postDelayed(this,1000);}};

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        paths=new AppPaths(this);runtime=GameRuntime.get(this);prefs=getSharedPreferences("launch",MODE_PRIVATE);
        try{paths.ensure();}catch(IOException e){Toast.makeText(this,e.getMessage(),Toast.LENGTH_LONG).show();}
        if(Build.VERSION.SDK_INT>=33&&checkSelfPermission("android.permission.POST_NOTIFICATIONS")!=android.content.pm.PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"},9);
        ScrollView scroll=new ScrollView(this);scroll.setBackgroundColor(0xff070b10);
        LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setPadding(dp(20),dp(16),dp(20),dp(24));
        scroll.addView(root);
        TextView title=new TextView(this);title.setText("X3: Albion Prelude · LxXRM");title.setTextSize(24);title.setTextColor(0xffe6edf3);title.setTypeface(Typeface.DEFAULT_BOLD);
        root.addView(title);
        statusView=text(root,"",0xff4cc2ff,14);

        LinearLayout runtimeCard=card(root,"1 · Runtime");
        runtimeView=text(runtimeCard,"",0xffc9d4df,14);
        LinearLayout runtimeRow=row(runtimeCard);
        button(runtimeRow,"Download runtime (338 MB)",v->operation("Runtime download",()->RuntimeInstaller.installOnline(paths,this::progress)));
        button(runtimeRow,"Install from file…",v->pick(new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"),PICK_RUNTIME));
        mediaManifest=MediaAddon.manifest(this);
        LinearLayout mediaRow=row(runtimeCard);
        mediaButton=button(mediaRow,mediaManifest==null?"Media add-on unavailable in this build":"Download media add-on ("+MediaAddon.size(mediaManifest)+")",
            v->operation("Media add-on",()->MediaAddon.install(this,paths,this::progress)));

        LinearLayout gameCard=card(root,"2 · Game files");
        gameView=text(gameCard,"",0xffc9d4df,14);
        LinearLayout gameRow=row(gameCard);
        button(gameRow,"Import X3 folder…",v->pick(new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE),PICK_GAME));
        button(gameRow,"Sync changed files",v->sync());
        cancel=button(gameRow,"Cancel",v->{cancelRequested=true;operationStatus="Cancelling…";});
        skipArchives=check(gameCard,"Leave out LxXRM installer archives (_DOWNLOADS folders, not needed once the mod is applied)",
            prefs.getBoolean("skip_installer_archives",true));
        skipArchives.setOnCheckedChangeListener((b,on)->prefs.edit().putBoolean("skip_installer_archives",on).apply());

        LinearLayout launchCard=card(root,"3 · Launch");
        label(launchCard,"Program (X3AP.exe plays; choose SETUP.bat or another tool to run it in Wine)");
        program=spinner(launchCard,Collections.singletonList("X3AP.exe"));
        label(launchCard,"Arguments (-skipintro skips the intro movies)");
        arguments=new EditText(this);arguments.setSingleLine(true);arguments.setTextColor(0xffe6edf3);arguments.setText(prefs.getString("arguments","-skipintro"));launchCard.addView(arguments);
        label(launchCard,"Resolution");resolution=spinner(launchCard,GameRuntime.RESOLUTIONS);
        label(launchCard,"Graphics");renderer=spinner(launchCard,Arrays.asList("Turnip + DXVK (Adreno GPU)","Software (WineD3D, slow)"));
        label(launchCard,"Turnip driver");turnip=spinner(launchCard,Arrays.asList("24.3.4","26.0.0"));
        label(launchCard,"Display updates per second");fps=spinner(launchCard,Arrays.asList("60","30"));
        label(launchCard,"Display path (native surface: frames straight to the screen, the X server no longer encodes them; experimental)");
        presentation=spinner(launchCard,Arrays.asList("RFB","Native surface"));
        label(launchCard,"CPU emulation (fast is the default; fastest is an experiment: back to fast if X3 hangs, balanced if fast does)");
        cpu=spinner(launchCard,Arrays.asList("fast","fastest","balanced","accurate"));
        audio=check(launchCard,"Sound",prefs.getBoolean("audio",true));
        hud=check(launchCard,"DXVK FPS overlay",prefs.getBoolean("dxvk_hud",true));
        diagnostics=check(launchCard,"Verbose Wine logging, next launch only (slower)",prefs.getBoolean("diagnostic_logging",false));
        soundDiagnostics=check(launchCard,"Media diagnostics, next launch only (much slower: traces every sound and video call)",prefs.getBoolean("sound_diagnostics",false));
        passthrough=check(launchCard,"Let X3 also read the gamepad itself (XInput). Off: only the app's layered controls reach the game",
            prefs.getBoolean("controller_passthrough",false));
        select(resolution,prefs.getString("resolution","1280x720"));select(renderer,prefs.getString("renderer_label","Turnip + DXVK (Adreno GPU)"));
        select(turnip,prefs.getString("turnip_driver","24.3.4"));select(fps,prefs.getString("display_fps","60"));select(presentation,prefs.getString("presentation","RFB"));select(cpu,prefs.getString("cpu_profile_v3","fast"));
        LinearLayout launchRow=row(launchCard);
        button(launchRow,"Launch",v->launch());
        button(launchRow,"Show game",v->{if(runtime.alive())startActivity(new Intent(this,GameActivity.class));else Toast.makeText(this,"The game is not running",Toast.LENGTH_SHORT).show();});
        button(launchRow,"Stop",v->operation("Stopping game",()->runtime.stop()));

        LinearLayout tools=card(root,"4 · Controls and maintenance");
        LinearLayout toolsRow=row(tools);
        button(toolsRow,"Controller mappings",v->{controller.capture(false);new ControllerDialog(this,controller,()->{}).show();});
        button(toolsRow,"Reset controls to X3 default",v->{try{controller.resetToDefault();Toast.makeText(this,"X3 + LxXRM default restored",Toast.LENGTH_SHORT).show();}catch(Exception e){Toast.makeText(this,e.getMessage(),Toast.LENGTH_LONG).show();}});
        LinearLayout toolsRow2=row(tools);
        button(toolsRow2,"Export logs…",v->pick(new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/zip").putExtra(Intent.EXTRA_TITLE,"x3-logs-"+System.currentTimeMillis()+".zip"),EXPORT_LOGS));
        button(toolsRow2,"Reset Wine prefix",v->new AlertDialog.Builder(this).setTitle("Reset the Wine prefix?")
            .setMessage("The current prefix is moved to a backup folder inside the app, not deleted, and the next launch builds a fresh one. X3 saves and settings (Documents/Egosoft) are kept: they are stored outside the prefix.")
            .setPositiveButton("Reset",(d,w)->operation("Resetting prefix",()->{File b=runtime.resetPrefix();operationStatus=b==null?"No prefix yet":"Prefix moved to "+b.getName();}))
            .setNegativeButton("Cancel",null).show());
        TextView notes=text(tools,"Tips: untick EAX in X3's launcher window (most likely cause of silent audio under Wine). Saves and settings are kept in app storage, separate from the prefix and the runtime. "
            +"The first launch builds the Wine prefix and DXVK caches, so it is slower than later ones. Hold Select in game for the controller help overlay.",0xff8b98a8,12);
        notes.setPadding(0,dp(8),0,0);

        setContentView(scroll);
        controller=new ControllerManager(this,paths.controllerProfile(),event->{});
        refreshPrograms();
    }

    @Override protected void onResume(){super.onResume();refreshPrograms();handler.post(tick);}
    @Override protected void onPause(){handler.removeCallbacks(tick);saveOptions();super.onPause();}
    @Override protected void onDestroy(){if(controller!=null)controller.close();worker.shutdown();super.onDestroy();}

    private void progress(String text){operationStatus=text;}

    interface Op {void run()throws Exception;}
    private void operation(String label,Op op) {
        if(operationRunning){Toast.makeText(this,"Wait for: "+operationStatus,Toast.LENGTH_SHORT).show();return;}
        operationRunning=true;cancelRequested=false;operationStatus=label+"…";
        SessionService.Busy.begin();
        try{SessionService.ensure(this);}catch(RuntimeException e){Logs.failure(paths.logs,"session_service",e);}
        worker.execute(()->{
            try{op.run();if(operationStatus.endsWith("…"))operationStatus=label+" finished";}
            catch(Exception e){operationStatus=label+" failed: "+e.getMessage();Logs.failure(paths.logs,label,e);}
            finally{SessionService.Busy.end();operationRunning=false;handler.post(()->{refreshPrograms();refresh();});}
        });
    }

    private void sync() {
        String tree=importRecord().optString("tree","");
        if(tree.isEmpty()){Toast.makeText(this,"Import the X3 folder first",Toast.LENGTH_SHORT).show();return;}
        Uri uri=Uri.parse(tree);
        boolean skip=skipArchives.isChecked();
        operation("Sync",()->{JSONObject r=GameImporter.run(this,uri,paths,true,skip,importProgress());operationStatus="Sync finished: "+r.optLong("copied")+" files updated, "+r.optLong("skipped")+" unchanged";});
    }

    private GameImporter.Progress importProgress(){return new GameImporter.Progress(){
        public void update(String text){operationStatus=text;}
        public boolean cancelled(){return cancelRequested;}
    };}

    private void launch() {
        saveOptions();
        JSONObject options=new JSONObject();
        try {
            options.put("program",String.valueOf(program.getSelectedItem())).put("arguments",arguments.getText().toString())
                .put("resolution",String.valueOf(resolution.getSelectedItem()))
                .put("renderer",renderer.getSelectedItemPosition()==0?"turnip":"software")
                .put("turnip_driver",String.valueOf(turnip.getSelectedItem())).put("display_fps",Integer.parseInt(String.valueOf(fps.getSelectedItem())))
                .put("presentation_mode",presentation.getSelectedItemPosition()==1?"native_surface":"rfb")
                .put("cpu_profile",String.valueOf(cpu.getSelectedItem())).put("audio",audio.isChecked()).put("dxvk_hud",hud.isChecked())
                .put("diagnostic_logging",diagnostics.isChecked()).put("sound_diagnostics",soundDiagnostics.isChecked())
                .put("controller_passthrough",passthrough.isChecked());
        }catch(org.json.JSONException e){return;}
        // Diagnostics are for one run: left on, they slow every later game down (one run with media
        // traces wrote 4.4 GB of log).
        diagnostics.setChecked(false);soundDiagnostics.setChecked(false);saveOptions();
        operation("Launching",()->{runtime.start(options);operationStatus="Game running";handler.post(()->startActivity(new Intent(this,GameActivity.class)));});
    }

    private void saveOptions() {
        if(program==null)return;
        prefs.edit().putString("program",String.valueOf(program.getSelectedItem())).putString("arguments",arguments.getText().toString())
            .putString("resolution",String.valueOf(resolution.getSelectedItem())).putString("renderer_label",String.valueOf(renderer.getSelectedItem()))
            .putString("turnip_driver",String.valueOf(turnip.getSelectedItem())).putString("display_fps",String.valueOf(fps.getSelectedItem()))
            .putString("presentation",String.valueOf(presentation.getSelectedItem()))
            .putString("cpu_profile_v3",String.valueOf(cpu.getSelectedItem())).putBoolean("audio",audio.isChecked()).putBoolean("dxvk_hud",hud.isChecked())
            .putBoolean("diagnostic_logging",diagnostics.isChecked()).putBoolean("sound_diagnostics",soundDiagnostics.isChecked())
            .putBoolean("controller_passthrough",passthrough.isChecked()).apply();
    }

    private JSONObject importRecord() {
        File file=paths.importRecord();
        if(!file.isFile()||file.length()>65536)return new JSONObject();
        try{return new JSONObject(new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8));}catch(Exception e){return new JSONObject();}
    }

    private void refreshPrograms() {
        if(program==null)return;
        List<String> found=runtime.programs();
        if(found.isEmpty())found=Collections.singletonList("X3AP.exe");
        String wanted=prefs.getString("program","X3AP.exe");
        program.setAdapter(adapter(found));select(program,wanted);
    }

    private void refresh() {
        boolean installed=RuntimeInstaller.installed(paths);
        String media=MediaAddon.installedVersion(paths);boolean mediaCurrent=MediaAddon.current(paths,mediaManifest);
        runtimeView.setText((installed?"Installed: Debian arm64 · Box64 0.4.4 · Wine 10.0 WoW64 (TRASC client runtime v1)":"Not installed. Download it once (about 338 MB, needs ~1.5 GB free while unpacking).")
            +(!installed?"":mediaCurrent?"\nMedia add-on: installed ("+media+") · music, voices and movies enabled"
                :media!=null?"\nMedia add-on: "+media+" installed; this build expects "+mediaManifest.optString("version")+" (download to update)"
                :"\nMedia add-on: not installed · only sound effects play (music, voices and movies need it)"));
        if(mediaButton!=null){mediaButton.setEnabled(installed&&mediaManifest!=null&&!mediaCurrent&&!operationRunning);
            if(mediaCurrent)mediaButton.setText("Media add-on installed ✓");}
        JSONObject record=importRecord();
        if(paths.game.isDirectory()&&record.length()>0){
            StringBuilder text=new StringBuilder(String.format(Locale.ROOT,"Imported: %d files · %.1f GB · %s",record.optInt("files"),record.optLong("bytes")/1e9,record.optString("imported_utc")));
            if(!record.optBoolean("addon_folder"))text.append("\n⚠ No addon/ folder: Albion Prelude data may be missing.");
            JSONObject exe=record.optJSONObject("x3ap");
            if(exe!=null&&exe.has("machine")){
                text.append("\nX3AP.exe: ").append("i386".equals(exe.optString("machine"))?"32-bit":exe.optString("machine"))
                    .append(exe.optBoolean("steam_api")?" · ⚠ Steam build (imports steam_api.dll): it needs the Steam client, which is not in the app. Use the NoSteam X3AP.exe."
                        :" · NoSteam build ✓")
                    .append(exe.optBoolean("large_address_aware")?" · 4 GB aware":" · 2 GB limit (not Large Address Aware)");
            } else if(exe!=null&&exe.has("error"))text.append("\n⚠ X3AP.exe: ").append(exe.optString("error"));
            org.json.JSONArray left=record.optJSONArray("skipped_folders");
            if(left!=null&&left.length()>0){text.append("\nLeft out:");for(int i=0;i<left.length();i++)text.append(i==0?" ":", ").append(left.optString(i));}
            gameView.setText(text);
        } else gameView.setText("Not imported. Pick the folder on your device that contains X3AP.exe (the \"X3 Terran Conflict\" folder with addon/ inside). It is copied into app storage for speed.");
        String game=runtime.alive()?"Game running":runtime.status;
        JSONObject launch=runtime.launchState();
        if(launch!=null&&runtime.alive())game="Game: "+launch.optString("phase").replace('_',' ')+(launch.has("error")?" · "+launch.optString("error"):"");
        statusView.setText((operationRunning?operationStatus:operationStatus.isEmpty()?"Ready":operationStatus)+"\n"+game);
        cancel.setVisibility(operationRunning?View.VISIBLE:View.GONE);
    }

    private void pick(Intent intent,int code){try{startActivityForResult(intent,code);}catch(ActivityNotFoundException e){Toast.makeText(this,"No file picker available",Toast.LENGTH_LONG).show();}}

    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        if(result!=RESULT_OK||data==null||data.getData()==null)return;
        Uri uri=data.getData();
        if(request==PICK_GAME){
            try{getContentResolver().takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION);}catch(SecurityException ignored){}
            if(runtime.alive()){Toast.makeText(this,"Stop the game before importing",Toast.LENGTH_LONG).show();return;}
            boolean skip=skipArchives.isChecked();
            operation("Import",()->{JSONObject r=GameImporter.run(this,uri,paths,false,skip,importProgress());operationStatus=String.format(Locale.ROOT,"Imported %d files (%.1f GB)",r.optInt("files"),r.optLong("bytes")/1e9);});
        } else if(request==PICK_RUNTIME){
            operation("Runtime install",()->{try(InputStream in=getContentResolver().openInputStream(uri)){if(in==null)throw new IOException("Cannot read the selected file");RuntimeInstaller.installOffline(paths,in,this::progress);}});
        } else if(request==EXPORT_LOGS){
            operation("Log export",()->{
                JSONObject meta=new JSONObject().put("version",BuildConfig.VERSION_NAME).put("created_utc",java.time.Instant.now().toString())
                    .put("device",Build.MANUFACTURER+" "+Build.MODEL).put("android_sdk",Build.VERSION.SDK_INT).put("runtime_installed",RuntimeInstaller.installed(paths))
                    .put("import",importRecord()).put("game_running",runtime.alive()).put("status",runtime.status);
                File last=new File(paths.work,"last-launch.json");
                if(last.isFile()&&last.length()<65536)meta.put("last_launch",new JSONObject(new String(Files.readAllBytes(last.toPath()),StandardCharsets.UTF_8)));
                try(OutputStream out=getContentResolver().openOutputStream(uri)){if(out==null)throw new IOException("Cannot write the selected file");Logs.export(paths.logs,meta,out);}
                operationStatus="Logs exported";
            });
        }
    }

    /** Gamepad: A activates the focused control, B goes back; the D-pad moves focus natively. */
    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        if(event.getKeyCode()==KeyEvent.KEYCODE_BUTTON_A){
            dispatchKeyEvent(new KeyEvent(event.getDownTime(),event.getEventTime(),event.getAction(),KeyEvent.KEYCODE_DPAD_CENTER,event.getRepeatCount()));return true;
        }
        if(event.getKeyCode()==KeyEvent.KEYCODE_BUTTON_B){if(event.getAction()==KeyEvent.ACTION_UP)onBackPressed();return true;}
        return super.dispatchKeyEvent(event);
    }

    // --- small view helpers ---
    private int dp(int v){return Math.round(v*getResources().getDisplayMetrics().density);}
    private GradientDrawable shape(int color,int radius){GradientDrawable g=new GradientDrawable();g.setColor(color);g.setCornerRadius(dp(radius));return g;}
    private LinearLayout card(LinearLayout parent,String heading){
        LinearLayout card=new LinearLayout(this);card.setOrientation(LinearLayout.VERTICAL);card.setPadding(dp(16),dp(12),dp(16),dp(14));card.setBackground(shape(0xff111a25,14));
        LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(-1,-2);params.topMargin=dp(14);parent.addView(card,params);
        TextView h=new TextView(this);h.setText(heading);h.setTextSize(17);h.setTypeface(Typeface.DEFAULT_BOLD);h.setTextColor(0xffe6edf3);card.addView(h);
        return card;
    }
    private LinearLayout row(LinearLayout parent){LinearLayout row=new LinearLayout(this);row.setOrientation(LinearLayout.HORIZONTAL);parent.addView(row);return row;}
    private TextView text(LinearLayout parent,String value,int color,int size){TextView t=new TextView(this);t.setText(value);t.setTextColor(color);t.setTextSize(size);t.setPadding(0,dp(4),0,dp(4));parent.addView(t);return t;}
    private void label(LinearLayout parent,String value){TextView t=text(parent,value,0xff8b98a8,13);t.setPadding(0,dp(8),0,0);}
    private Button button(LinearLayout parent,String title,View.OnClickListener action){
        Button b=new Button(this);b.setText(title);b.setAllCaps(false);b.setTextColor(Color.WHITE);
        b.setBackground(new RippleDrawable(ColorStateList.valueOf(0x44ffffff),shape(0xff1d2b3b,10),null));b.setOnClickListener(action);
        LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(-2,dp(48));params.setMargins(0,dp(8),dp(10),0);parent.addView(b,params);return b;
    }
    private ArrayAdapter<String> adapter(List<String> items){return new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,new ArrayList<>(items));}
    private Spinner spinner(LinearLayout parent,List<String> items){Spinner s=new Spinner(this);s.setAdapter(adapter(items));parent.addView(s);return s;}
    private CheckBox check(LinearLayout parent,String title,boolean checked){CheckBox c=new CheckBox(this);c.setText(title);c.setTextColor(0xffe6edf3);c.setChecked(checked);parent.addView(c);return c;}
    private static void select(Spinner spinner,String value){
        for(int i=0;i<spinner.getCount();i++)if(String.valueOf(spinner.getItemAtPosition(i)).equals(value)){spinner.setSelection(i);return;}
    }
}
