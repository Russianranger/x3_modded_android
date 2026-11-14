package io.github.russianranger.x3;

import android.content.Context;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Locale;

/**
 * Optional GStreamer add-on for the runtime: lets Wine's winegstreamer decode what X3 plays through
 * DirectShow (music, comms voices, movies). Built and tested in CI on the pinned runtime image
 * (scripts/build_media_addon.sh) and published once as a release; the APK carries its manifest
 * (assets/payload/media-addon.json) so the download is checked against the hash CI produced.
 *
 * Installed state is runtime/etc/x3-media-addon.json, written last, equal to the manifest. The
 * runner reads it to switch winegstreamer on. Reinstalling the runtime removes the add-on.
 */
final class MediaAddon {
    static final String ASSET="payload/media-addon.json",MARKER="etc/x3-media-addon.json";
    private MediaAddon(){}

    /** The manifest this APK was built with, or null if the build carries none. */
    static JSONObject manifest(Context context){
        try(InputStream in=context.getAssets().open(ASSET)){
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[8192];int n;
            while((n=in.read(b))>0&&out.size()<65536)out.write(b,0,n);
            JSONObject manifest=new JSONObject(out.toString("UTF-8"));
            if(manifest.optInt("format")!=1||manifest.optString("sha256").length()!=64||manifest.optLong("bytes")<=0
                ||!manifest.optString("url").startsWith("https://")
                ||!manifest.optString("runtime_sha256").equalsIgnoreCase(RuntimeInstaller.SHA256))return null;
            return manifest;
        }catch(Exception e){return null;}
    }

    /** Version of the add-on unpacked in the runtime, or null. */
    static String installedVersion(AppPaths paths){
        File marker=new File(paths.runtime,MARKER);
        if(!marker.isFile()||marker.length()>65536)return null;
        try{
            JSONObject installed=new JSONObject(new String(Files.readAllBytes(marker.toPath()),StandardCharsets.UTF_8));
            return installed.optInt("format")==1?installed.optString("version",null):null;
        }catch(Exception e){return null;}
    }

    static boolean current(AppPaths paths,JSONObject manifest){
        return manifest!=null&&manifest.optString("version").equals(installedVersion(paths));
    }

    static String size(JSONObject manifest){
        return String.format(Locale.ROOT,"%d MB",(manifest.optLong("bytes")+(1<<20)-1)>>20);
    }

    static void install(Context context,AppPaths paths,RuntimeInstaller.Progress progress)throws Exception {
        JSONObject manifest=manifest(context);
        if(manifest==null)throw new IOException("This build has no media add-on manifest");
        if(!RuntimeInstaller.installed(paths))throw new IOException("Install the runtime first");
        File archive=new File(paths.cache,"media-addon-arm64.tar.gz");
        try{
            RuntimeInstaller.download(manifest.getString("url"),archive,manifest.getLong("bytes"),"Downloading media add-on",progress);
            progress.update("Verifying media add-on…");
            if(!manifest.getString("sha256").equalsIgnoreCase(RuntimeInstaller.sha256(archive)))
                throw new IOException("Media add-on checksum does not match; download again");
            File marker=new File(paths.runtime,MARKER);
            if(!marker.delete()&&marker.exists())throw new IOException("Could not reset the add-on marker");
            TarExtractor.overlay(archive,paths.runtime,n->progress.update("Unpacking media add-on · "+n+" files"),2L*1024*1024*1024);
            File temporary=new File(paths.runtime,MARKER+".tmp");
            try(OutputStream out=new FileOutputStream(temporary)){out.write(manifest.toString(1).getBytes(StandardCharsets.UTF_8));}
            if(!temporary.renameTo(marker))throw new IOException("Could not record the add-on");
        }finally{archive.delete();}
    }
}
