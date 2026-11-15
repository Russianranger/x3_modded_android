// Adapted from trasc-server-android ClientRuntime.java start()/stop() (commit 99e8c86f).
// X3 changes: no server/profile coupling; program chosen from the imported game folder; assets
// are staged once per APK install; the session request matches runner/x3_runner.py.
package io.github.russianranger.x3;

import android.content.Context;
import android.content.pm.PackageInfo;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;
import java.util.concurrent.TimeUnit;

final class GameRuntime {
    private static GameRuntime instance;
    static synchronized GameRuntime get(Context context){if(instance==null)instance=new GameRuntime(context.getApplicationContext());return instance;}
    static final List<String> RESOLUTIONS=Arrays.asList("1280x720","1600x900","1920x1080","1366x768","1024x768","800x600");
    private static final String[] RUNNER={"x3_runner.py","client_audio.py","client_vulkan.py","client_presentation.py","client_xauthority.py",
        "client_metrics.py","log_retention.py","runtime_probe.py","pe_info.py"};
    private static final String[] PAYLOAD={"libasound_module_pcm_trasc.so","audio-bundle.json","turnip.so","turnip-26.0.0.so","vulkan-probe",
        "dxvk-d3d9.dll","dxvk-d3d9-x64.dll","vulkan-bundle.json","wineserver","wineserver-patch.json","x11-frame-bridge","presentation-bundle.json",
        "payload-provenance.json","box64","box64-build.json","x3pin.exe","wintools-build.json","amstream.dll","winegstreamer.dll","wine-dlls.json"};
    private static final String[] EXECUTABLE={"vulkan-probe","wineserver","x11-frame-bridge","box64"};
    final Context context;
    final AppPaths paths;
    final TransientPaths transientPaths;
    volatile boolean busy;
    volatile String status="Stopped";
    private volatile Process process;
    private volatile AudioBridge audio;

    private GameRuntime(Context context){this.context=context;paths=new AppPaths(context);transientPaths=new TransientPaths(paths.files);}
    boolean alive(){return process!=null&&process.isAlive();}
    File displaySocket(){return new File(transientPaths.run,"display.sock");}
    File inputSocket(){return new File(transientPaths.run,"input.sock");}

    JSONObject launchState() {
        File report=new File(transientPaths.run,"status.json");
        if(!report.isFile()||report.length()>262144)return null;
        try{return new JSONObject(new String(Files.readAllBytes(report.toPath()),StandardCharsets.UTF_8));}catch(Exception e){return null;}
    }

    /** Arguments split on spaces; double quotes group words. */
    static List<String> splitArguments(String text) {
        List<String> out=new ArrayList<>();StringBuilder current=new StringBuilder();boolean quoted=false,any=false;
        for(char c:text.toCharArray()){
            if(c=='"'){quoted=!quoted;any=true;}
            else if(Character.isWhitespace(c)&&!quoted){if(any||current.length()>0){out.add(current.toString());current.setLength(0);any=false;}}
            else current.append(c);
        }
        if(any||current.length()>0)out.add(current.toString());
        return out;
    }

    /** .exe/.bat/.cmd files in the game root and one folder deep, X3AP.exe first. */
    List<String> programs() {
        List<String> found=new ArrayList<>();
        File[] top=paths.game.listFiles();if(top==null)return found;
        Arrays.sort(top);
        for(File f:top){
            if(f.isFile()&&isProgram(f.getName()))found.add(f.getName());
            else if(f.isDirectory()){File[] inner=f.listFiles();if(inner==null)continue;Arrays.sort(inner);
                for(File g:inner)if(g.isFile()&&isProgram(g.getName())&&found.size()<200)found.add(f.getName()+"/"+g.getName());}
        }
        found.sort((a,b)->Boolean.compare(!a.equalsIgnoreCase("X3AP.exe"),!b.equalsIgnoreCase("X3AP.exe")));
        return found;
    }
    private static boolean isProgram(String name){String n=name.toLowerCase(Locale.ROOT);return n.endsWith(".exe")||n.endsWith(".bat")||n.endsWith(".cmd");}

    private void stageAssets()throws Exception {
        PackageInfo info=context.getPackageManager().getPackageInfo(context.getPackageName(),0);
        long version=android.os.Build.VERSION.SDK_INT>=28?info.getLongVersionCode():info.versionCode;
        String stamp=version+":"+info.lastUpdateTime;
        File marker=new File(paths.backend,".staged");
        if(marker.isFile()&&new String(Files.readAllBytes(marker.toPath()),StandardCharsets.UTF_8).equals(stamp))return;
        status="Preparing bundled runtime helpers…";
        TarExtractor.remove(paths.backend);paths.backend.mkdirs();
        for(String name:RUNNER)copyAsset("runner/"+name,new File(paths.backend,name));
        for(String name:PAYLOAD)copyAsset("payload/"+name,new File(paths.backend,name));
        for(String name:EXECUTABLE)if(!new File(paths.backend,name).setExecutable(true,true))throw new IOException("Could not prepare "+name);
        Files.write(marker.toPath(),stamp.getBytes(StandardCharsets.UTF_8));
    }
    private void copyAsset(String asset,File target)throws IOException {
        try(InputStream in=context.getAssets().open(asset);OutputStream out=new FileOutputStream(target)){byte[] b=new byte[1024*1024];int n;while((n=in.read(b))>0)out.write(b,0,n);}
    }

    synchronized JSONObject start(JSONObject options)throws Exception {
        if(busy)throw new IOException("Another operation is running");
        if(alive())throw new IOException("The game is already running. Show it, or stop it first.");
        if(!RuntimeInstaller.installed(paths))throw new IOException("Install the runtime first");
        if(!paths.game.isDirectory())throw new IOException("Import your X3 folder first");
        busy=true;boolean started=false;
        try {
            paths.ensure();
            String program=options.optString("program","X3AP.exe");
            if(!new File(paths.game,program).isFile())throw new IOException("Program not found in the imported folder: "+program);
            String resolution=options.optString("resolution","1280x720");
            if(!RESOLUTIONS.contains(resolution))throw new IOException("Unsupported resolution");
            String renderer=options.optString("renderer","turnip");
            JSONObject request=new JSONObject()
                .put("mode",program.equalsIgnoreCase("X3AP.exe")?"game":"program").put("program",program)
                .put("arguments",new JSONArray(splitArguments(options.optString("arguments",""))))
                .put("resolution",resolution).put("renderer",renderer)
                .put("turnip_driver",options.optString("turnip_driver","24.3.4"))
                .put("presentation_mode","rfb").put("display_fps",options.optInt("display_fps",60))
                .put("audio",options.optBoolean("audio",true)).put("dxvk_hud",options.optBoolean("dxvk_hud",true))
                .put("cpu_profile",options.optString("cpu_profile","fast")).put("cpu_affinity","available")
                .put("runtime_mode",options.optString("runtime_mode","auto"))
                .put("diagnostic_logging",options.optBoolean("diagnostic_logging",false))
                .put("sound_diagnostics",options.optBoolean("sound_diagnostics",false))
                .put("controller_passthrough",options.optBoolean("controller_passthrough",false));
            transientPaths.prepare();paths.prefix.mkdirs();paths.saves.mkdirs();
            stageAssets();
            File run=transientPaths.run,tmp=transientPaths.tmp,root=paths.runtime;
            Files.write(new File(root,"etc/hosts").toPath(),"127.0.0.1 localhost\n::1 localhost\n".getBytes(StandardCharsets.UTF_8));
            Files.write(new File(root,"etc/resolv.conf").toPath(),"nameserver 1.1.1.1\n".getBytes(StandardCharsets.UTF_8));
            File nativeDir=new File(context.getApplicationInfo().nativeLibraryDir);
            File proot=new File(nativeDir,"libproot.so");
            if(!proot.canExecute())throw new IOException("This APK is missing its ARM64 runtime launcher");
            List<String> command=new ArrayList<>(Arrays.asList(proot.getPath(),"--kill-on-exit","--sysvipc","-0","-r",root.getPath(),
                "-b",new File(paths.backend,"wineserver").getPath()+":/opt/wine/bin/wineserver",
                // Patched build of the runtime's own Box64 commit (patches/box64; runner verifies its hash).
                "-b",new File(paths.backend,"box64").getPath()+":/usr/local/bin/box64",
                // Patched Wine 10.0 builtins (patches/wine): comms video and audio formats in amstream,
                // seeking in winegstreamer's DirectShow decoders. The runner checks both hashes.
                "-b",new File(paths.backend,"amstream.dll").getPath()+":/opt/wine/lib/wine/i386-windows/amstream.dll",
                "-b",new File(paths.backend,"winegstreamer.dll").getPath()+":/opt/wine/lib/wine/i386-windows/winegstreamer.dll",
                "-b","/dev","-b","/proc","-b","/sys",
                "-b",paths.game.getPath()+":/game","-b",paths.prefix.getPath()+":/prefix","-b",paths.saves.getPath()+":/saves","-b",run.getPath()+":/session",
                "-b",paths.logs.getPath()+":/logs","-b",paths.backend.getPath()+":/opt/x3","-b",tmp.getPath()+":/tmp",
                "-w","/game","/usr/bin/env","-i","HOME=/root","USER=root","PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "LANG=C.UTF-8","TMPDIR=/tmp","PYTHONUNBUFFERED=1","/usr/bin/python3","/opt/x3/x3_runner.py"));
            ProcessBuilder builder=new ProcessBuilder(command);
            builder.environment().put("PROOT_LOADER",new File(nativeDir,"libproot-loader.so").getPath());
            builder.environment().put("PROOT_TMP_DIR",tmp.getPath());
            boolean accelerated=false;
            File probeLog=new File(paths.logs,"x3-runtime-probe.log");
            if(request.getString("runtime_mode").equals("auto")) {
                status="Checking faster runtime file access…";
                List<String> probe=new ArrayList<>(command);probe.set(probe.size()-1,"/opt/x3/runtime_probe.py");
                accelerated=ProotAcceleration.preflight(probe,builder.environment(),probeLog,20000);
            }
            ProotAcceleration.configure(builder.environment(),accelerated);
            request.put("runtime_acceleration",accelerated?"seccomp":"compatibility");
            Files.write(new File(run,"request.json").toPath(),request.toString(2).getBytes(StandardCharsets.UTF_8));
            if(request.getBoolean("audio"))audio=AudioBridge.start(context,new File(run,"audio.sock"),new File(paths.logs,"x3-audio.log"));
            File prootLog=new File(paths.logs,"x3-proot.log");Logs.rotate(prootLog);
            builder.redirectErrorStream(true);builder.redirectOutput(prootLog);
            process=builder.start();started=true;status="Starting display and Wine…";
            Files.write(new File(paths.work,"last-launch.json").toPath(),request.toString(2).getBytes(StandardCharsets.UTF_8));
            final Process active=process;final AudioBridge playback=audio;
            Thread monitor=new Thread(()->{
                try{active.waitFor();}catch(InterruptedException ignored){}
                synchronized(GameRuntime.this){if(playback!=null&&audio==playback){playback.close();audio=null;}if(process==active)status="Game stopped";}
            },"x3-session-monitor");monitor.setDaemon(true);monitor.start();
            for(int i=0;i<300;i++) {
                JSONObject state=launchState();
                if(state!=null&&state.optString("phase").equals("error"))throw new IOException(state.optString("error"));
                if(!process.isAlive())throw new IOException("Runtime exited during startup. Export logs (x3-proot.log).");
                if(displaySocket().exists()){status="Display open · Wine is preparing (the first launch can take a few minutes)";return state==null?new JSONObject():state;}
                Thread.sleep(100);
            }
            throw new IOException("Display startup timed out; export logs");
        } catch(Exception e){
            Logs.failure(paths.logs,"game_start",e);status=e.getMessage();
            if(started&&alive())try{stopLocked();}catch(Exception cleanup){e.addSuppressed(cleanup);}
            else if(audio!=null){audio.close();audio=null;}
            throw e;
        } finally {busy=false;}
    }

    synchronized void stop()throws Exception {stopLocked();}
    private void stopLocked()throws Exception {
        Process active=process;
        if(active!=null&&active.isAlive()) {
            status="Stopping the game…";
            Files.write(new File(transientPaths.run,"stop").toPath(),"stop\n".getBytes(StandardCharsets.UTF_8));
            if(!active.waitFor(25,TimeUnit.SECONDS)){active.destroy();if(!active.waitFor(5,TimeUnit.SECONDS)){active.destroyForcibly();active.waitFor(5,TimeUnit.SECONDS);}}
        }
        if(audio!=null){audio.close();audio=null;}
        process=null;status="Game stopped";
    }

    /** Move the prefix aside so the next launch builds a fresh one. Saves stay in paths.saves. */
    synchronized File resetPrefix()throws IOException {
        if(alive()||busy)throw new IOException("Stop the game first");
        if(!paths.prefix.exists())return null;
        paths.backups.mkdirs();
        File backup=new File(paths.backups,"prefix-"+System.currentTimeMillis());
        if(!paths.prefix.renameTo(backup))throw new IOException("Could not move the Wine prefix aside");
        return backup;
    }
}
