package io.github.russianranger.x3;

import android.content.Context;
import java.io.File;
import java.io.IOException;

/** Every app-private location in one place. Nothing here lives on shared (FUSE) storage. */
final class AppPaths {
    final File files,work,logs,runtime,runtimeStaging,runtimePrevious,gameRoot,game,gameIncoming,prefix,backups,backend,cache;
    AppPaths(Context context) {
        files=context.getFilesDir();cache=context.getCacheDir();
        work=new File(files,"work");logs=new File(work,"logs");
        runtime=new File(files,"runtime");runtimeStaging=new File(files,"runtime-install");runtimePrevious=new File(files,"runtime-previous");
        gameRoot=new File(files,"game");game=new File(gameRoot,"current");gameIncoming=new File(gameRoot,"incoming");
        prefix=new File(gameRoot,"prefix");backups=new File(gameRoot,"backups");
        backend=new File(files,"backend");
    }
    void ensure()throws IOException {
        for(File dir:new File[]{work,logs,gameRoot,backups})
            if(!dir.isDirectory()&&!dir.mkdirs())throw new IOException("Cannot prepare app storage: "+dir);
    }
    File controllerProfile(){return new File(work,"controller.json");}
    File importRecord(){return new File(gameRoot,"import.json");}
}
