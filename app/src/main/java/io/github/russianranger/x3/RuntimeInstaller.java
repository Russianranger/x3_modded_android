// Adapted from trasc-server-android ClientRuntime.installOnline/activate and RuntimeManager.download
// (commit 99e8c86f). The archive is TRASC's published client runtime, pinned by SHA-256.
package io.github.russianranger.x3;

import org.json.JSONObject;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Locale;

/** Debian arm64 rootfs with Box64 0.4.4, Wine 10.0 WoW64, TigerVNC and Python. */
final class RuntimeInstaller {
    static final String URL_ARCHIVE="https://github.com/Russianranger/trasc-server-android/releases/download/client-runtime-v1/client-runtime-arm64.tar.gz";
    static final String SHA256="2f130c07683e50bc606af111d5c35c4f503c1427772c1f9b0f45e1e4b75c76c4";
    static final long BYTES=353710680L;
    interface Progress {void update(String text);}
    private RuntimeInstaller(){}

    static boolean installed(AppPaths paths){return new File(paths.runtime,"etc/trasc-client-runtime.json").isFile();}

    static void installOnline(AppPaths paths,Progress progress)throws Exception {
        File archive=new File(paths.cache,"client-runtime-arm64.tar.gz");
        try {
            download(URL_ARCHIVE,archive,progress);
            progress.update("Verifying runtime download…");
            if(!SHA256.equalsIgnoreCase(sha256(archive)))throw new IOException("Runtime checksum does not match; download again");
            activate(paths,archive,progress);
        } finally {archive.delete();}
    }

    static void installOffline(AppPaths paths,InputStream source,Progress progress)throws Exception {
        File archive=new File(paths.cache,"client-runtime-offline.tar.gz");
        try {
            progress.update("Copying runtime archive…");
            copy(source,archive,BYTES+1024*1024,BYTES,progress,"Copying runtime archive");
            progress.update("Verifying runtime archive…");
            if(!SHA256.equalsIgnoreCase(sha256(archive)))throw new IOException("This is not the pinned client-runtime-arm64.tar.gz (checksum mismatch)");
            activate(paths,archive,progress);
        } finally {archive.delete();}
    }

    private static void activate(AppPaths paths,File archive,Progress progress)throws Exception {
        File root=paths.runtime,staging=paths.runtimeStaging,previous=paths.runtimePrevious;
        if(!root.exists()&&previous.exists()&&!previous.renameTo(root))throw new IOException("Could not recover the previous runtime");
        TarExtractor.remove(staging);staging.mkdirs();
        try {
            TarExtractor.extract(archive,staging,n->progress.update("Unpacking runtime · "+n+" files"));
            File markerFile=new File(staging,"etc/trasc-client-runtime.json");
            if(markerFile.length()>8192)throw new IOException("Invalid runtime marker");
            JSONObject marker=new JSONObject(new String(Files.readAllBytes(markerFile.toPath()),StandardCharsets.UTF_8));
            if(marker.getInt("format")!=1||!marker.getString("architecture").equals("arm64")||!marker.getString("runtime").equals("client-1.0"))
                throw new IOException("Unexpected runtime archive");
            for(String file:new String[]{"usr/bin/python3.11","usr/bin/Xtigervnc","usr/local/bin/box64","opt/wine/bin/wine","opt/wine/bin/wineserver"})
                if(!new File(staging,file).isFile())throw new IOException("Runtime is incomplete: "+file);
            TarExtractor.remove(previous);
            if(root.exists()&&!root.renameTo(previous))throw new IOException("Could not preserve the previous runtime");
            if(!staging.renameTo(root)){if(previous.exists())previous.renameTo(root);throw new IOException("Could not activate the runtime");}
            TarExtractor.remove(previous);
            progress.update("Runtime installed.");
        } finally {TarExtractor.remove(staging);}
    }

    private static void download(String address,File target,Progress progress)throws Exception {
        download(address,target,BYTES,"Downloading runtime",progress);
    }

    /** HTTPS download of a file of known size (redirects followed, size enforced). */
    static void download(String address,File target,long bytes,String label,Progress progress)throws Exception {
        URL url=new URL(address);HttpURLConnection connection=null;
        for(int redirect=0;redirect<6;redirect++) {
            if(!url.getProtocol().equals("https"))throw new IOException("HTTPS is required");
            connection=(HttpURLConnection)url.openConnection();connection.setConnectTimeout(30000);connection.setReadTimeout(60000);
            connection.setInstanceFollowRedirects(false);connection.setRequestProperty("User-Agent","X3-Modded-Android/"+BuildConfig.VERSION_NAME);
            int code=connection.getResponseCode();
            if(code>=300&&code<400){String location=connection.getHeaderField("Location");connection.disconnect();url=new URL(url,location);continue;}
            if(code!=200){connection.disconnect();throw new IOException("Download returned HTTP "+code+". Try again, or install the archive from a file.");}
            long size=connection.getContentLengthLong();
            if(size>0&&size!=bytes){connection.disconnect();throw new IOException("Unexpected download size "+size+" (expected "+bytes+")");}
            try(InputStream in=connection.getInputStream()){copy(in,target,bytes,bytes,progress,label);}
            finally{connection.disconnect();}
            return;
        }
        throw new IOException("Too many download redirects");
    }

    private static void copy(InputStream in,File target,long limit,long expected,Progress progress,String label)throws IOException {
        target.getParentFile().mkdirs();
        if(target.getParentFile().getUsableSpace()<expected*3+512L*1024*1024)
            throw new IOException(String.format(Locale.ROOT,"Not enough free storage: about %d MB is needed to download and unpack this",(expected*3>>20)+512));
        long done=0,reported=0;
        try(OutputStream out=new FileOutputStream(target)) {
            byte[] b=new byte[1024*1024];int n;
            while((n=in.read(b))!=-1){
                done+=n;if(done>limit)throw new IOException("Download is larger than expected");
                out.write(b,0,n);
                if(done-reported>=8L*1024*1024){reported=done;progress.update(String.format(Locale.ROOT,"%s · %d / %d MB",label,done>>20,expected>>20));}
            }
        }
    }

    static String sha256(File file)throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try(InputStream in=new FileInputStream(file)){byte[] b=new byte[1024*1024];int n;while((n=in.read(b))!=-1)digest.update(b,0,n);}
        StringBuilder text=new StringBuilder();for(byte x:digest.digest())text.append(String.format(Locale.ROOT,"%02x",x&255));
        return text.toString();
    }
}
