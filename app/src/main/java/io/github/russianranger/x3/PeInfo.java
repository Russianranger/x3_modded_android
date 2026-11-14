package io.github.russianranger.x3;

import java.io.*;
import java.util.*;

/**
 * Read-only facts about a Windows executable. Java port of runner/pe_info.py; CI checks that both
 * give the same answers (tests/pe_fixtures.py + tests/java/PeInfoCheck.java).
 *
 * The launcher uses it to tell the NoSteam X3AP.exe from the Steam one by what the executable
 * imports, not by whether steam_api.dll sits in the folder: a Steam install keeps that DLL next to a
 * NoSteam executable. Every offset is bounds-checked; nothing is executed or modified.
 */
final class PeInfo {
    static final int MAX_HEADER=16*1024*1024;
    static final class Info {
        final String machine;final boolean largeAddressAware,gui,steamApi;final List<String> imports;
        Info(String machine,boolean laa,boolean gui,List<String> imports){
            this.machine=machine;largeAddressAware=laa;this.gui=gui;this.imports=Collections.unmodifiableList(imports);
            boolean steam=false;for(String name:imports){String n=name.toLowerCase(Locale.ROOT);if(n.equals("steam_api.dll")||n.equals("steam_api64.dll"))steam=true;}
            steamApi=steam;
        }
    }
    private PeInfo(){}

    static Info inspect(File file)throws IOException {
        byte[] data;
        try(InputStream in=new FileInputStream(file)){
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[65536];int n;
            while(out.size()<MAX_HEADER&&(n=in.read(buffer,0,Math.min(buffer.length,MAX_HEADER-out.size())))>0)out.write(buffer,0,n);
            data=out.toByteArray();
        }
        return inspect(data);
    }

    static Info inspect(byte[] data)throws IOException {
        if(data.length<2||data[0]!='M'||data[1]!='Z')throw new IOException("not a Windows executable");
        int pe=u32(data,0x3C);
        if(pe<0||pe+4>data.length||data[pe]!='P'||data[pe+1]!='E'||data[pe+2]!=0||data[pe+3]!=0)throw new IOException("invalid PE signature");
        int machine=u16(data,pe+4),sections=u16(data,pe+6),optionalSize=u16(data,pe+20),characteristics=u16(data,pe+22);
        int optional=pe+24,magic=u16(data,optional),directories;
        if(magic==0x10B)directories=optional+96;else if(magic==0x20B)directories=optional+112;else throw new IOException("unknown optional header");
        int subsystem=u16(data,optional+68);
        int table=optional+optionalSize;
        int count=Math.min(sections,96);long[][] spans=new long[count][];
        for(int i=0;i<count;i++){int base=table+40*i;spans[i]=new long[]{u32l(data,base+12),Math.max(u32l(data,base+8),u32l(data,base+16)),u32l(data,base+20)};}
        List<String> imports=new ArrayList<>();
        long importRva=u32l(data,directories+8);
        if(importRva!=0){
            long cursor=offsetOf(spans,importRva);
            while(imports.size()<256){
                if(cursor+20>data.length)break;
                boolean empty=true;for(int i=0;i<20;i++)if(data[(int)cursor+i]!=0){empty=false;break;}
                if(empty)break;
                imports.add(cString(data,offsetOf(spans,u32l(data,(int)cursor+12))));
                cursor+=20;
            }
        }
        String name=machine==0x14C?"i386":machine==0x8664?"x86_64":machine==0xAA64?"arm64":"0x"+Integer.toHexString(machine);
        return new Info(name,(characteristics&0x20)!=0,subsystem==2,imports);
    }

    private static long offsetOf(long[][] spans,long rva)throws IOException {
        for(long[] s:spans)if(s[0]<=rva&&rva<s[0]+s[1])return s[2]+rva-s[0];
        throw new IOException("address outside sections");
    }
    private static String cString(byte[] data,long offset)throws IOException {
        if(offset<0||offset>=data.length)throw new IOException("bad import name");
        int start=(int)offset,limit=(int)Math.min(data.length,offset+256);
        for(int i=start;i<limit;i++)if(data[i]==0){
            // Same as Python's decode('ascii','replace'): bytes above 0x7f become U+FFFD.
            StringBuilder name=new StringBuilder(i-start);for(int j=start;j<i;j++)name.append(data[j]>=0?(char)data[j]:(char)0xFFFD);
            return name.toString();
        }
        throw new IOException("bad import name");
    }
    private static int u16(byte[] d,int o)throws IOException {if(o<0||o+2>d.length)throw new IOException("truncated header");return (d[o]&0xff)|(d[o+1]&0xff)<<8;}
    private static long u32l(byte[] d,int o)throws IOException {if(o<0||o+4>d.length)throw new IOException("truncated header");return (d[o]&0xffL)|(d[o+1]&0xffL)<<8|(d[o+2]&0xffL)<<16|(d[o+3]&0xffL)<<24;}
    private static int u32(byte[] d,int o)throws IOException {long v=u32l(d,o);if(v>Integer.MAX_VALUE)throw new IOException("truncated header");return (int)v;}
}
