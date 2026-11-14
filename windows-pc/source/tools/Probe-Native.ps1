param([Parameter(Mandatory=$true)][string]$Directory)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Dependency-Common.ps1')
Assert-XStagePlatform
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class XStageNativeProbe {
 [DllImport("kernel32",CharSet=CharSet.Unicode,SetLastError=true)] public static extern IntPtr LoadLibraryEx(string p,IntPtr r,uint f);
 [DllImport("kernel32",CharSet=CharSet.Ansi,ExactSpelling=true)] public static extern IntPtr GetProcAddress(IntPtr h,string n);
 [DllImport("kernel32")] public static extern bool FreeLibrary(IntPtr h);
 [UnmanagedFunctionPointer(CallingConvention.StdCall)] public delegate uint Version();
 public static uint ReadVersion(IntPtr h,string n) {var p=GetProcAddress(h,n);if(p==IntPtr.Zero)throw new Exception("Missing export: "+n);return ((Version)Marshal.GetDelegateForFunctionPointer(p,typeof(Version)))();}
}
'@
$handles = @()
try {
    foreach ($item in @(@('bass.dll','BASS_GetVersion'),@('bassmidi.dll','BASS_MIDI_GetVersion'),@('bass_fx.dll','BASS_FX_GetVersion'))) {
        $path=[IO.Path]::GetFullPath((Join-Path $Directory $item[0]));Assert-XStagePE $path
        $handle=[XStageNativeProbe]::LoadLibraryEx($path,[IntPtr]::Zero,0x1100)
        if ($handle -eq [IntPtr]::Zero) { throw ('Cannot load '+$path+' Win32='+[Runtime.InteropServices.Marshal]::GetLastWin32Error()) }
        $handles += $handle
        $version=[XStageNativeProbe]::ReadVersion($handle,$item[1])
        if (($version -shr 16) -ne 0x204) { throw ('Incompatible BASS API version: '+$path) }
        Write-Host ($item[0]+' loaded: 0x'+$version.ToString('X8'))
    }
} finally { [array]::Reverse($handles); foreach ($handle in $handles) { $null=[XStageNativeProbe]::FreeLibrary($handle) } }
