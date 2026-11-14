// Adapted from trasc-server-android ServerService.java (commit 99e8c86f).
package io.github.russianranger.x3;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.os.*;

/** Keeps the process alive (foreground + partial wake lock) during imports, downloads and play. */
public final class SessionService extends Service {
    static final String STOP="io.github.russianranger.x3.STOP_GAME";
    private PowerManager.WakeLock lock;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final Runnable idleCheck=new Runnable(){@Override public void run(){
        if(!Busy.active()&&!GameRuntime.get(SessionService.this).alive()){stopSelf();return;}
        handler.postDelayed(this,5000);
    }};

    /** Long operations register here so the service knows when it may stop. */
    static final class Busy {
        private static int count;
        static synchronized void begin(){count++;}
        static synchronized void end(){count=Math.max(0,count-1);}
        static synchronized boolean active(){return count>0;}
    }

    static void ensure(Context context) {
        Intent intent=new Intent(context,SessionService.class);
        context.startForegroundService(intent);
    }

    @Override public void onCreate(){
        super.onCreate();
        NotificationManager nm=getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel("session","Game session",NotificationManager.IMPORTANCE_LOW));
        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop=PendingIntent.getService(this,1,new Intent(this,SessionService.class).setAction(STOP),PendingIntent.FLAG_IMMUTABLE);
        Notification notification=new Notification.Builder(this,"session").setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle("X3 Modded").setContentText("Game, import or download active · tap to open")
            .setContentIntent(open).addAction(new Notification.Action.Builder(null,"Stop game",stop).build()).setOngoing(true).build();
        if(Build.VERSION.SDK_INT>=34)startForeground(1,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(1,notification);
        lock=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"X3:session");
        lock.acquire(12L*60*60*1000);
        handler.postDelayed(idleCheck,5000);
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        if(intent!=null&&STOP.equals(intent.getAction()))new Thread(()->{
            try{GameRuntime.get(this).stop();}catch(Exception e){Logs.failure(new AppPaths(this).logs,"notification_stop",e);}
        },"x3-notification-stop").start();
        return START_NOT_STICKY;
    }
    @Override public void onDestroy(){handler.removeCallbacksAndMessages(null);if(lock!=null&&lock.isHeld())lock.release();super.onDestroy();}
    @Override public IBinder onBind(Intent intent){return null;}
}
