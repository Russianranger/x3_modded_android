package io.github.russianranger.x3;

import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Bounded log rotation, failure records and the shareable log bundle. */
final class Logs {
    private static final long MAX_FILE=64L*1024*1024;
    private Logs(){}

    /** Keep one previous copy of a closed log. */
    static void rotate(File log) {
        try {
            if(Files.isSymbolicLink(log.toPath())||!log.isFile()||log.length()==0)return;
            String name=log.getName();int dot=name.lastIndexOf('.');
            File previous=new File(log.getParentFile(),(dot>0?name.substring(0,dot):name)+".previous"+(dot>0?name.substring(dot):""));
            Files.move(log.toPath(),previous.toPath(),StandardCopyOption.REPLACE_EXISTING);
        }catch(IOException ignored){}
    }

    static synchronized void failure(File logs,String operation,Throwable error) {
        try {
            logs.mkdirs();File file=new File(logs,"app-failures.log");
            if(file.length()>512*1024)rotate(file);
            StringWriter trace=new StringWriter();error.printStackTrace(new PrintWriter(trace));
            String text=java.time.Instant.now()+" "+operation+": "+trace.toString().substring(0,Math.min(8192,trace.toString().length()))+"\n";
            try(FileOutputStream out=new FileOutputStream(file,true)){out.write(text.getBytes(StandardCharsets.UTF_8));}
        }catch(IOException ignored){android.util.Log.e("X3",operation,error);}
    }

    /** Zip every regular file under logs/ plus app metadata. No game files, saves or credentials. */
    static void export(File logs,JSONObject metadata,OutputStream target)throws IOException {
        try(ZipOutputStream zip=new ZipOutputStream(new BufferedOutputStream(target))) {
            zip.putNextEntry(new ZipEntry("metadata.json"));
            try{zip.write(metadata.toString(2).getBytes(StandardCharsets.UTF_8));}catch(org.json.JSONException e){throw new IOException(e);}
            zip.closeEntry();
            File[] files=logs.listFiles();
            if(files!=null)for(File file:files) {
                if(Files.isSymbolicLink(file.toPath())||!file.isFile()||file.length()>MAX_FILE)continue;
                zip.putNextEntry(new ZipEntry("logs/"+file.getName()));
                try(InputStream in=new FileInputStream(file)){byte[] b=new byte[65536];int n;while((n=in.read(b))>0)zip.write(b,0,n);}
                zip.closeEntry();
            }
        }
    }
}
