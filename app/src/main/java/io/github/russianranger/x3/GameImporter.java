package io.github.russianranger.x3;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/**
 * Copies the X3 folder the user picks (Storage Access Framework) into app-private internal
 * storage. Running from shared storage goes through Android's FUSE layer on every file access;
 * a private copy avoids that (docs/05-loading-times.md).
 *
 * Fresh import: copy into game/incoming, then swap with game/current (old copy removed only after
 * success). Sync: copy only files whose size or modification time changed; nothing is deleted.
 */
final class GameImporter {
    interface Progress {void update(String text);boolean cancelled();}
    static final class Entry {final String path,documentId;final long size,modified;Entry(String p,String d,long s,long m){path=p;documentId=d;size=s;modified=m;}}
    private static final String[] COLUMNS={DocumentsContract.Document.COLUMN_DOCUMENT_ID,DocumentsContract.Document.COLUMN_DISPLAY_NAME,
        DocumentsContract.Document.COLUMN_MIME_TYPE,DocumentsContract.Document.COLUMN_SIZE,DocumentsContract.Document.COLUMN_LAST_MODIFIED};
    private static final int MAX_FILES=400000;
    private GameImporter(){}

    static JSONObject run(Context context,Uri tree,AppPaths paths,boolean sync,Progress progress)throws Exception {
        ContentResolver resolver=context.getContentResolver();
        String rootId=DocumentsContract.getTreeDocumentId(tree);
        progress.update("Looking for X3AP.exe…");
        String baseId=findGameFolder(resolver,tree,rootId);
        progress.update("Scanning game files…");
        List<String> directories=new ArrayList<>();List<Entry> files=new ArrayList<>();
        scan(resolver,tree,baseId,directories,files,progress);
        long total=0;for(Entry e:files)total+=e.size;
        File destination=sync?paths.game:paths.gameIncoming;
        if(sync&&!paths.game.isDirectory())throw new IOException("Import the game once before syncing changes");
        if(!sync)TarExtractor.remove(paths.gameIncoming);
        long needed=sync?0:total;
        if(sync)for(Entry e:files){File f=target(destination,e.path);if(!unchanged(f,e))needed+=e.size;}
        if(paths.files.getUsableSpace()<needed+1024L*1024*1024)
            throw new IOException(String.format(Locale.ROOT,"Not enough free storage: %.1f GB needed plus 1 GB headroom",needed/1e9));
        if(!destination.isDirectory()&&!destination.mkdirs())throw new IOException("Cannot create "+destination);
        for(String dir:directories){File d=target(destination,dir);if(!d.isDirectory()&&!d.mkdirs())throw new IOException("Cannot create folder "+dir);}
        long copied=0,copiedBytes=0,skipped=0,lastReport=0;int index=0;
        byte[] buffer=new byte[1024*1024];
        for(Entry e:files) {
            if(progress.cancelled())throw new InterruptedIOException("Import cancelled; the previous game copy is unchanged");
            index++;File out=target(destination,e.path);
            if(sync&&unchanged(out,e)){skipped++;continue;}
            Uri document=DocumentsContract.buildDocumentUriUsingTree(tree,e.documentId);
            File temporary=new File(out.getParentFile(),"."+out.getName()+".x3-part");
            try(InputStream in=resolver.openInputStream(document);OutputStream os=new FileOutputStream(temporary)) {
                if(in==null)throw new IOException("Cannot read "+e.path);
                int n;while((n=in.read(buffer))>0){os.write(buffer,0,n);copiedBytes+=n;
                    if(copiedBytes-lastReport>=32L*1024*1024){lastReport=copiedBytes;progress.update(String.format(Locale.ROOT,"%s %d / %d files · %.2f / %.2f GB",sync?"Syncing":"Copying",index,files.size(),copiedBytes/1e9,(sync?needed:total)/1e9));}}
            }
            Files.move(temporary.toPath(),out.toPath(),StandardCopyOption.REPLACE_EXISTING);
            if(e.modified>0)out.setLastModified(e.modified);
            copied++;
        }
        if(!sync){
            progress.update("Activating imported game…");
            TarExtractor.remove(paths.game);
            if(!paths.gameIncoming.renameTo(paths.game))throw new IOException("Could not activate the imported game");
        }
        JSONObject record=new JSONObject().put("tree",tree.toString()).put("files",files.size()).put("bytes",total)
            .put("imported_utc",java.time.Instant.now().toString()).put("mode",sync?"sync":"fresh")
            .put("copied",copied).put("skipped",skipped)
            .put("steam_api_dll",new File(paths.game,"steam_api.dll").isFile()).put("addon_folder",new File(paths.game,"addon").isDirectory());
        File recordFile=paths.importRecord();
        Files.write(recordFile.toPath(),record.toString(2).getBytes(StandardCharsets.UTF_8));
        return record;
    }

    private static boolean unchanged(File file,Entry e){return file.isFile()&&file.length()==e.size&&(e.modified<=0||Math.abs(file.lastModified()-e.modified)<2000);}

    private static File target(File root,String relative)throws IOException {
        File file=new File(root,relative).getCanonicalFile();
        if(!file.toPath().startsWith(root.getCanonicalFile().toPath()))throw new IOException("Unsafe path in game folder: "+relative);
        return file;
    }

    private static boolean safeName(String name){return name!=null&&!name.isEmpty()&&!name.equals(".")&&!name.equals("..")&&name.indexOf('/')<0&&name.indexOf('\0')<0&&name.length()<=255;}

    /** The picked folder, or its only child folder, must contain X3AP.exe. */
    private static String findGameFolder(ContentResolver resolver,Uri tree,String rootId)throws IOException {
        List<String[]> children=list(resolver,tree,rootId);
        for(String[] c:children)if(!isDirectory(c)&&"x3ap.exe".equalsIgnoreCase(c[1]))return rootId;
        List<String> candidates=new ArrayList<>();
        for(String[] c:children)if(isDirectory(c))for(String[] g:list(resolver,tree,c[0]))if(!isDirectory(g)&&"x3ap.exe".equalsIgnoreCase(g[1]))candidates.add(c[0]);
        if(candidates.size()==1)return candidates.get(0);
        throw new IOException("Choose the folder that contains X3AP.exe (your \"X3 Terran Conflict\" folder, with addon/ inside).");
    }

    private static boolean isDirectory(String[] row){return DocumentsContract.Document.MIME_TYPE_DIR.equals(row[2]);}

    /** Rows: id, name, mime, size, modified. */
    private static List<String[]> list(ContentResolver resolver,Uri tree,String parentId)throws IOException {
        Uri children=DocumentsContract.buildChildDocumentsUriUsingTree(tree,parentId);
        List<String[]> rows=new ArrayList<>();
        try(Cursor cursor=resolver.query(children,COLUMNS,null,null,null)) {
            if(cursor==null)throw new IOException("Cannot list folder");
            while(cursor.moveToNext())rows.add(new String[]{cursor.getString(0),cursor.getString(1),cursor.getString(2),
                cursor.isNull(3)?"0":String.valueOf(cursor.getLong(3)),cursor.isNull(4)?"0":String.valueOf(cursor.getLong(4))});
        }
        return rows;
    }

    private static void scan(ContentResolver resolver,Uri tree,String baseId,List<String> directories,List<Entry> files,Progress progress)throws IOException {
        ArrayDeque<String[]> pending=new ArrayDeque<>();pending.add(new String[]{baseId,""});
        while(!pending.isEmpty()) {
            if(progress.cancelled())throw new InterruptedIOException("Import cancelled");
            String[] next=pending.removeFirst();
            for(String[] row:list(resolver,tree,next[0])) {
                if(!safeName(row[1]))throw new IOException("Unsupported file name in game folder: "+row[1]);
                String path=next[1].isEmpty()?row[1]:next[1]+"/"+row[1];
                if(isDirectory(row)){directories.add(path);pending.add(new String[]{row[0],path});}
                else{files.add(new Entry(path,row[0],Long.parseLong(row[3]),Long.parseLong(row[4])));
                    if(files.size()>MAX_FILES)throw new IOException("Game folder has too many files");
                    if(files.size()%2000==0)progress.update("Scanning game files · "+files.size());}
            }
        }
    }
}
